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

    @property
    def is_degenerate(self) -> bool:
        """True when the picture had no detail to hash, and the fingerprint means nothing.

        A pHash sets one bit per frequency above the median, so a real photograph always
        lands on half of them. A flat frame — a black story, a blank export — has no
        median to split and collapses onto a near-empty hash, which then sits at distance
        zero from every other flat frame on the internet. One such frame put 118 false
        `confirmed` in a report, and this is the line that keeps it out."""
        bits = 4 * len(self.value)
        return abs(bin(int(self.value, 16)).count("1") - bits // 2) > bits // 4

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


@dataclass(frozen=True, slots=True)
class Lead:
    """A candidate that was named and would not come down.

    Not every unproven trace deserves this. Vision also lists pages it merely associates
    with the subject, and measured against the ones we could check, 9.6% of its page-level
    claims hold — a landscape comes back with thirty-five YouTube videos. Those are noise
    and are dropped. These are different: the engine pointed at an actual image, and the
    site refused to serve it (tiktok, Facebook's lookaside). One such trace, checked by
    hand, was the photo it claimed to be.

    It is still not a finding. It is a place to go and look."""

    page_url: str
    title: str | None = None

    @property
    def domain(self) -> str | None:
        host = urlparse(self.page_url or "").hostname or ""
        return host.removeprefix("www.").lower() or None


@dataclass(frozen=True, slots=True)
class SearchAnswer:
    """What an engine said about one photo: the matches, and the words it said them in.

    The payload is kept verbatim because every filter in this project is a judgement call
    that will be got wrong at least once. Without it, correcting one means paying for the
    whole search again; with it, the correction is a re-read of a string."""

    matches: tuple[Match, ...]
    payload: str


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
"""Platforms whose hits are not worth carrying, and the honest reason why.

It is not "these are yours": a repost by a stranger is a finding wherever it happens.
It is that Instagram and Threads hand their images to nobody — `lookaside.instagram.com`
answers a login wall to every agent — so nothing found there can ever be compared, and
an unverifiable hit belongs in the leads, not in the report.

Facebook is not on this list, and used to be, on the "these are yours" reasoning. A
stranger reposting your picture in a Facebook group is exactly what this tool exists to
find, and `lookaside.fbsbx.com` does serve the image of any public post — so blocking it
cost real findings. If you cross-post to your own page, `--ignore-domain facebook.com`."""


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
class Unverified:
    """One of your photos, and the places that could not be checked either way."""

    photo: Photo
    leads: tuple[Lead, ...]


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
    unverified: tuple[Unverified, ...] = ()
