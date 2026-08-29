"""The rules of the problem, with no idea that databases or HTTP exist.

Two questions live here and nowhere else: when are two pictures the same picture,
and how much do we trust a match. Everything else is plumbing.
"""

from __future__ import annotations

import io
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, replace
from enum import Enum
from urllib.parse import urlparse

import imagehash
from PIL import Image, ImageFile

ImageFile.LOAD_TRUNCATED_IMAGES = True
Image.MAX_IMAGE_PIXELS = 200_000_000

SAME_PHOTO_DISTANCE = 6
"""Below this, two of your own files are the same shot: a carousel frame, a re-export."""

CONFIRMED_DISTANCE = 8
"""Below this, a candidate found online is your photo, merely recompressed."""

LIKELY_DISTANCE = 16
"""Below this it is your photo cropped, filtered or heavily edited. Above, it is not."""


@dataclass(frozen=True, slots=True)
class Fingerprint:
    """A perceptual hash. Comparable, unlike the bytes it came from."""

    value: str

    @classmethod
    def of(cls, image: bytes) -> Fingerprint:
        with Image.open(io.BytesIO(image)) as opened:
            return cls(str(imagehash.phash(opened.convert("RGB"), hash_size=8)))

    def distance_to(self, other: Fingerprint) -> int:
        return int(imagehash.hex_to_hash(self.value) - imagehash.hex_to_hash(other.value))

    def __str__(self) -> str:
        return self.value


class MatchKind(str, Enum):
    FULL = "full"
    PARTIAL = "partial"


class Verdict(str, Enum):
    PENDING = "pending"
    CONFIRMED = "confirmed"
    LIKELY = "likely"
    REJECTED = "rejected"
    UNREACHABLE = "unreachable"

    @property
    def worth_reporting(self) -> bool:
        return self in (Verdict.CONFIRMED, Verdict.LIKELY)


def verdict_for(distance: int) -> Verdict:
    if distance <= CONFIRMED_DISTANCE:
        return Verdict.CONFIRMED
    if distance <= LIKELY_DISTANCE:
        return Verdict.LIKELY
    return Verdict.REJECTED


@dataclass(frozen=True, slots=True)
class Photo:
    path: str
    fingerprint: Fingerprint
    id: int | None = None
    group_id: int | None = None

    @property
    def is_representative(self) -> bool:
        return self.id is not None and self.id == self.group_id


@dataclass(frozen=True, slots=True)
class Match:
    """Somewhere a search engine claims one of your photos appears."""

    kind: MatchKind
    image_url: str
    page_url: str | None = None
    title: str | None = None
    verdict: Verdict = Verdict.PENDING
    distance: int | None = None
    id: int | None = None

    def __post_init__(self) -> None:
        # A claim we cannot fetch is a claim we cannot check, and the whole point of
        # this tool is that nothing reaches the report unverified. Search engines do
        # return page-only hits; they are dominated by topical noise (a photo of a
        # cloud comes back with pages *about* cumulus) and there is no way to tell
        # those from a real one. So they are not matches, and cannot be built.
        if not self.image_url:
            raise ValueError("a match needs an image url, or it can never be verified")

    @property
    def domain(self) -> str | None:
        target = self.page_url or self.image_url
        host = urlparse(target or "").hostname or ""
        return host.removeprefix("www.").lower() or None

    @property
    def target(self) -> str:
        """Where to send a reader: the page if we know it, the image otherwise."""
        return self.page_url or self.image_url

    def judged(self, distance: int) -> Match:
        return replace(self, verdict=verdict_for(distance), distance=distance)

    def unreachable(self) -> Match:
        return replace(self, verdict=Verdict.UNREACHABLE, distance=None)


OWN_PLATFORMS = frozenset(
    {
        "instagram.com",
        "cdninstagram.com",
        "threads.net",
        "threads.com",
        "whatsapp.com",
        "messenger.com",
    }
)
"""Finding your photo on Instagram is not a finding. Neither is its own CDN.

Facebook is not on this list, and used to be. A stranger reposting your picture in a
Facebook group is exactly what this tool exists to find, and `lookaside.fbsbx.com`
serves the image of *any* public post, not just your own — so blocking it cost real
findings. If you cross-post to your own page, `--ignore-domain facebook.com`."""


def is_own_platform(domain: str | None, platforms: Iterable[str] = OWN_PLATFORMS) -> bool:
    if not domain:
        return False
    return any(domain == p or domain.endswith(f".{p}") for p in platforms)


def group_by_similarity(
    fingerprints: Sequence[tuple[int, Fingerprint]],
    threshold: int = SAME_PHOTO_DISTANCE,
) -> dict[int, int]:
    """Map every photo id to the id of the photo that represents its group.

    Greedy: each photo joins the first representative it is close enough to, otherwise it
    becomes one. Order-dependent by construction, which is why callers feed it a stable
    order — the alternative is clustering, and at album scale it buys nothing.
    """
    representatives: list[tuple[int, Fingerprint]] = []
    assignment: dict[int, int] = {}
    for photo_id, fingerprint in fingerprints:
        match = next(
            (
                rep_id
                for rep_id, rep in representatives
                if rep.distance_to(fingerprint) <= threshold
            ),
            None,
        )
        if match is None:
            representatives.append((photo_id, fingerprint))
            match = photo_id
        assignment[photo_id] = match
    return assignment


@dataclass(frozen=True, slots=True)
class Finding:
    """One of your photos, and every place it was confirmed to appear."""

    photo: Photo
    copies: int
    matches: tuple[Match, ...]


@dataclass(frozen=True, slots=True)
class Summary:
    photos: int
    unique: int
    searched: int
    tally: dict[Verdict, int]

    @property
    def duplicates_saved(self) -> int:
        return self.photos - self.unique


@dataclass(frozen=True, slots=True)
class Report:
    summary: Summary
    findings: tuple[Finding, ...]
