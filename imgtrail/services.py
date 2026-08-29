"""Use cases. They orchestrate ports and domain rules, and know no concrete technology."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass

from .domain import (
    OWN_PLATFORMS,
    SAME_PHOTO_DISTANCE,
    Finding,
    Fingerprint,
    Match,
    Photo,
    Report,
    Summary,
    Verdict,
    group_by_similarity,
    is_own_platform,
)
from .ports import (
    ImageFetcher,
    ImageLoader,
    MatchRepository,
    PhotoRepository,
    PhotoSource,
    SearchEngine,
)


@dataclass(frozen=True, slots=True)
class IndexResult:
    added: int
    total: int
    unique: int
    unreadable: int

    @property
    def duplicates_saved(self) -> int:
        return self.total - self.unique


@dataclass(frozen=True, slots=True)
class ScanPlan:
    """What a scan would do, priced, before it does it."""

    pending: tuple[Photo, ...]
    already_searched: int
    engine_name: str
    cost: float
    flat: int = 0
    """Photos left out because their fingerprint says nothing. Never worth paying for."""

    def __len__(self) -> int:
        return len(self.pending)


class ScanService:
    def __init__(
        self,
        photos: PhotoRepository,
        matches: MatchRepository,
        engine: SearchEngine,
        loader: ImageLoader,
        fetcher: ImageFetcher,
    ) -> None:
        self._photos = photos
        self._matches = matches
        self._engine = engine
        self._loader = loader
        self._fetcher = fetcher

    def index(self, source: PhotoSource, threshold: int = SAME_PHOTO_DISTANCE) -> IndexResult:
        """Fingerprint everything new, then collapse the near-duplicates into groups."""
        known = self._photos.known_references()
        added = unreadable = 0
        for reference in source.photos():
            if reference in known:
                continue
            try:
                fingerprint = Fingerprint.of(self._loader.load(reference))
            except (OSError, ValueError):
                unreadable += 1
                continue
            self._photos.add(Photo(path=reference, fingerprint=fingerprint))
            added += 1

        fingerprints = self._photos.fingerprints()
        assignment = group_by_similarity(fingerprints, threshold)
        self._photos.assign_groups(assignment)
        return IndexResult(
            added=added,
            total=len(fingerprints),
            unique=len(set(assignment.values())),
            unreadable=unreadable,
        )

    def plan(self, limit: int | None = None) -> ScanPlan:
        awaiting = self._photos.representatives_awaiting_search()
        pending = [photo for photo in awaiting if not photo.fingerprint.is_degenerate]
        flat = len(awaiting) - len(pending)
        if limit is not None:
            pending = pending[:limit]
        already = self._photos.counts().searched
        return ScanPlan(
            pending=tuple(pending),
            already_searched=already,
            engine_name=self._engine.name,
            cost=self._engine.estimated_cost(len(pending), already),
            flat=flat,
        )

    def search(
        self,
        plan: ScanPlan,
        own_platforms: Iterable[str] = OWN_PLATFORMS,
        on_batch: Callable[[int], None] | None = None,
    ) -> int:
        """Search each unique photo, keeping only matches outside your own platforms.

        Persistence happens per batch, so an interrupted run never loses a search you
        have already paid for.
        """
        platforms = frozenset(own_platforms)
        stored = 0
        batch = self._engine.batch_size
        for start in range(0, len(plan.pending), batch):
            chunk = plan.pending[start : start + batch]
            images = [self._loader.load(photo.path) for photo in chunk]
            for photo, matches in zip(chunk, self._engine.search(images), strict=True):
                assert photo.id is not None
                keep = [m for m in matches if not is_own_platform(m.domain, platforms)]
                stored += self._matches.add_all(photo.id, keep)
                self._photos.mark_searched(photo.id, self._engine.name)
            if on_batch:
                on_batch(len(chunk))
        return stored

    def verify(
        self,
        workers: int = 8,
        on_result: Callable[[], None] | None = None,
    ) -> dict[Verdict, int]:
        """Re-earn every match by fetching it and comparing against the original."""
        outstanding = self._matches.awaiting_verdict()
        tally: dict[Verdict, int] = {}
        if not outstanding:
            return tally

        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {
                pool.submit(self._judge, match, fingerprint): match
                for match, fingerprint in outstanding
            }
            for future in as_completed(futures):
                judged = future.result()
                self._matches.record(judged)
                tally[judged.verdict] = tally.get(judged.verdict, 0) + 1
                if on_result:
                    on_result()
        return tally

    def _judge(self, match: Match, original: Fingerprint) -> Match:
        downloaded = self._fetcher.fetch(match.image_url)
        if downloaded is None:
            return match.unreachable()
        try:
            return match.judged(original.distance_to(Fingerprint.of(downloaded)))
        except (OSError, ValueError):
            return match.unreachable()


class ReportService:
    def __init__(self, photos: PhotoRepository, matches: MatchRepository) -> None:
        self._photos = photos
        self._matches = matches

    def build(self, verdicts: Sequence[Verdict] | None = None) -> Report:
        wanted = verdicts or [v for v in Verdict if v.worth_reporting]
        rows = self._matches.findings(wanted)
        sizes = self._photos.group_sizes()
        photos = self._photos.by_ids(sorted({group_id for group_id, _ in rows}))

        by_group: dict[int, list[Match]] = {}
        for group_id, match in rows:
            by_group.setdefault(group_id, []).append(match)

        # A flat frame matches every other flat frame online, so its "findings" are an
        # artefact of the fingerprint, not a copy of anything. Dropped here as well as at
        # search time, which also cleans the reports of databases searched before the fix.
        findings = [
            Finding(photo=photos[group_id], copies=sizes.get(group_id, 1), matches=tuple(items))
            for group_id, items in by_group.items()
            if group_id in photos and not photos[group_id].fingerprint.is_degenerate
        ]
        findings.sort(key=lambda f: (-len(f.matches), f.photo.path))

        summary = self._photos.counts()
        return Report(
            summary=Summary(
                photos=summary.photos,
                unique=summary.unique,
                searched=summary.searched,
                tally=self._matches.tally(),
            ),
            findings=tuple(findings),
        )
