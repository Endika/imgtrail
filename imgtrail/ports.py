"""The boundaries. Everything above these is the application; everything below, a detail.

Each protocol is deliberately narrow: a service should not be able to reach a capability
it has no business using, and a fake should be a handful of lines.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from pathlib import Path
from typing import Protocol, runtime_checkable

from .domain import Fingerprint, Lead, Match, Photo, Report, SearchAnswer, Summary, Verdict


@runtime_checkable
class PhotoSource(Protocol):
    """Where your photos come from: an export archive, a folder, anything."""

    def photos(self) -> Iterator[str]:
        """Yield a stable reference per photo, in a deterministic order."""


@runtime_checkable
class ImageLoader(Protocol):
    def load(self, reference: str) -> bytes:
        """Read one photo back. Raises OSError if it cannot be read."""


@runtime_checkable
class SearchEngine(Protocol):
    """A reverse image search backend. Swapping Google for TinEye happens only here."""

    name: str
    batch_size: int
    free_units_per_month: int
    price_per_1k: float

    def search(self, images: Sequence[bytes]) -> list[SearchAnswer]:
        """Answer once per image, in the order given. Costs money; call it sparingly."""

    def parse(self, payload: str) -> SearchAnswer:
        """Re-read one of its own payloads. Free, and the reason payloads are kept."""

    def estimated_cost(self, units: int, already_used: int = 0) -> float:
        pass

    def close(self) -> None:
        pass


@runtime_checkable
class ImageFetcher(Protocol):
    def fetch(self, url: str) -> bytes | None:
        """Download a candidate. None when it is unreachable or is not an image."""


@runtime_checkable
class ResponseArchive(Protocol):
    """Keeps what a search engine answered, so re-reading it never costs a search."""

    def save(self, group_id: int, engine: str, payload: str) -> None:
        pass

    def all(self, engine: str) -> list[tuple[int, str]]:
        pass

    def answers_for(self, group_id: int) -> list[tuple[str, str]]:
        pass


@runtime_checkable
class PhotoRepository(Protocol):
    def add(self, photo: Photo) -> None:
        pass

    def known_references(self) -> set[str]:
        pass

    def fingerprints(self) -> list[tuple[int, Fingerprint]]:
        pass

    def assign_groups(self, assignment: dict[int, int]) -> None:
        pass

    def representatives_awaiting_search(
        self,
        under: str | None = None,
        engine: str | None = None,
        only_blank: bool = False,
    ) -> list[Photo]:
        pass

    def representatives(self, under: str | None = None, only_blank: bool = False) -> list[Photo]:
        pass

    def searched_this_month(self, engine: str | None = None) -> int:
        pass

    def searched_by(self, engine: str) -> int:
        pass

    def matching(self, fragment: str) -> list[Photo]:
        pass

    def mark_searched(self, group_id: int, engine: str) -> None:
        pass

    def counts(self) -> Summary:
        pass

    def by_ids(self, ids: Sequence[int]) -> dict[int, Photo]:
        pass

    def group_sizes(self) -> dict[int, int]:
        pass


@runtime_checkable
class MatchRepository(Protocol):
    def add_all(self, group_id: int, matches: Sequence[Match]) -> int:
        pass

    def matches_for(self, group_id: int) -> list[Match]:
        pass

    def leads(self) -> list[tuple[int, Lead]]:
        """Candidates that could not be downloaded. Derived, never written."""

    def awaiting_verdict(self) -> list[tuple[Match, Fingerprint]]:
        pass

    def record(self, match: Match) -> None:
        pass

    def findings(self, verdicts: Sequence[Verdict]) -> list[tuple[int, Match]]:
        pass

    def tally(self) -> dict[Verdict, int]:
        pass


@runtime_checkable
class ReportWriter(Protocol):
    def write(self, report: Report, destination: Path) -> None:
        pass
