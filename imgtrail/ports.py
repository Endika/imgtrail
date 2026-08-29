"""The boundaries. Everything above these is the application; everything below, a detail.

Each protocol is deliberately narrow: a service should not be able to reach a capability
it has no business using, and a fake should be a handful of lines.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from pathlib import Path
from typing import Protocol, runtime_checkable

from .domain import Fingerprint, Match, Photo, Report, SearchAnswer, Summary, Verdict


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

    def search(self, images: Sequence[bytes]) -> list[SearchAnswer]:
        """Answer once per image, in the order given. Costs money; call it sparingly."""

    def parse(self, payload: str) -> list[Match]:
        """Re-read one of its own payloads. Free, and the reason payloads are kept."""

    def estimated_cost(self, units: int, already_used: int = 0) -> float: ...

    def close(self) -> None: ...


@runtime_checkable
class ImageFetcher(Protocol):
    def fetch(self, url: str) -> bytes | None:
        """Download a candidate. None when it is unreachable or is not an image."""


@runtime_checkable
class ResponseArchive(Protocol):
    """Keeps what a search engine answered, so re-reading it never costs a search."""

    def save(self, group_id: int, engine: str, payload: str) -> None: ...
    def all(self) -> list[tuple[int, str]]: ...


@runtime_checkable
class PhotoRepository(Protocol):
    def add(self, photo: Photo) -> None: ...
    def known_references(self) -> set[str]: ...
    def fingerprints(self) -> list[tuple[int, Fingerprint]]: ...
    def assign_groups(self, assignment: dict[int, int]) -> None: ...
    def representatives_awaiting_search(self) -> list[Photo]: ...
    def representatives(self) -> list[Photo]: ...
    def searched_this_month(self) -> int: ...
    def mark_searched(self, group_id: int, engine: str) -> None: ...
    def counts(self) -> Summary: ...
    def by_ids(self, ids: Sequence[int]) -> dict[int, Photo]: ...
    def group_sizes(self) -> dict[int, int]: ...


@runtime_checkable
class MatchRepository(Protocol):
    def add_all(self, group_id: int, matches: Sequence[Match]) -> int: ...
    def awaiting_verdict(self) -> list[tuple[Match, Fingerprint]]: ...
    def record(self, match: Match) -> None: ...
    def findings(self, verdicts: Sequence[Verdict]) -> list[tuple[int, Match]]: ...
    def tally(self) -> dict[Verdict, int]: ...


@runtime_checkable
class ReportWriter(Protocol):
    def write(self, report: Report, destination: Path) -> None: ...
