"""Google Cloud Vision `WEB_DETECTION`, over plain REST with an API key.

Deliberately not the `google-cloud-vision` SDK: an API key is a two-minute setup, a
service account is not, and this endpoint is the only one we need.
"""

from __future__ import annotations

import base64
import io
import json
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import httpx
from PIL import Image

from imgtrail.domain import Match, MatchKind, SearchAnswer

ENDPOINT = "https://vision.googleapis.com/v1/images:annotate"
PRICE_PER_1K = 3.50
FREE_UNITS_PER_MONTH = 1000
MAX_UPLOAD_SIDE = 1280


def shrink(image: bytes, max_side: int = MAX_UPLOAD_SIDE) -> bytes:
    """Vision downscales server-side anyway; doing it here keeps a batch of 16 small."""
    with Image.open(io.BytesIO(image)) as opened:
        converted = opened.convert("RGB")
        if max(converted.size) > max_side:
            converted.thumbnail((max_side, max_side))
        buffer = io.BytesIO()
        converted.save(buffer, format="JPEG", quality=88)
        return buffer.getvalue()


def parse_web_detection(web: dict[str, Any]) -> list[Match]:
    """Flatten one Vision response into matches.

    `pagesWithMatchingImages` is the useful part: it pairs a page with the image on it.
    The top-level lists catch hosted copies Google never tied to a page — partial ones
    included, since a repost is usually a crop.

    Two kinds of entry are dropped on purpose. `visuallySimilarImages` means "looks
    alike", not "is your photo". And pages Vision lists without naming an image on them
    are topical associations, not copies: of its page-level claims that could be checked
    against the original, 9.6% held, and a landscape photo comes back with thirty-five
    YouTube videos. Neither can be verified, and neither is worth a reader's time.
    """
    matches: list[Match] = []
    seen: set[tuple[str | None, str | None]] = set()

    def push(kind: MatchKind, page: str | None, image: str | None, title: str | None) -> None:
        if image and (page, image) not in seen:
            seen.add((page, image))
            matches.append(Match(kind=kind, page_url=page, image_url=image, title=title))

    for page in web.get("pagesWithMatchingImages", []):
        url, title = page.get("url"), page.get("pageTitle")
        images = [(i.get("url"), MatchKind.FULL) for i in page.get("fullMatchingImages", [])]
        images += [(i.get("url"), MatchKind.PARTIAL) for i in page.get("partialMatchingImages", [])]
        for image_url, kind in images:
            push(kind, url, image_url, title)

    for image in web.get("fullMatchingImages", []):
        push(MatchKind.FULL, None, image.get("url"), None)

    for image in web.get("partialMatchingImages", []):
        push(MatchKind.PARTIAL, None, image.get("url"), None)

    return matches


@dataclass(frozen=True, slots=True)
class Explanation:
    """Everything one answer said, including the parts the parser throws away.

    The report is opinionated on purpose; this is the record it is an opinion about. It
    exists so "why is my photo not in there" is a question the tool answers itself, rather
    than one you answer by reading its source."""

    matches: tuple[Match, ...]
    unnamed_pages: tuple[str, ...]
    """Pages the engine listed without pointing at an image. Dropped: 9.6% of its
    page-level claims held when they could be checked at all."""
    similar: tuple[str, ...]
    """`visuallySimilarImages`. Dropped: semantic likeness is not a copy."""
    guess: str | None


def explain(payload: str) -> Explanation:
    web = json.loads(payload)
    unnamed = [
        page["url"]
        for page in web.get("pagesWithMatchingImages", [])
        if page.get("url")
        and not page.get("fullMatchingImages")
        and not page.get("partialMatchingImages")
    ]
    labels = web.get("bestGuessLabels", [])
    return Explanation(
        matches=tuple(parse_web_detection(web)),
        unnamed_pages=tuple(dict.fromkeys(unnamed)),
        similar=tuple(i["url"] for i in web.get("visuallySimilarImages", []) if i.get("url")),
        guess=labels[0].get("label") if labels else None,
    )


class MissingApiKey(RuntimeError):
    """Planning a scan is free; running one is not."""


class VisionSearchEngine:
    name = "google-vision"
    batch_size = 16  # Vision's per-request cap
    free_units_per_month = FREE_UNITS_PER_MONTH
    price_per_1k = PRICE_PER_1K

    def __init__(
        self,
        api_key: str = "",
        timeout: float = 60.0,
        client: httpx.Client | None = None,
        endpoint: str = ENDPOINT,
    ) -> None:
        self._key = api_key
        self._endpoint = endpoint
        self._client = client or httpx.Client(timeout=timeout)

    def close(self) -> None:
        self._client.close()

    def estimated_cost(self, units: int, already_used: int = 0) -> float:
        billable = max(0, units + already_used - FREE_UNITS_PER_MONTH)
        return round(billable * PRICE_PER_1K / 1000, 2)

    def parse(self, payload: str) -> SearchAnswer:
        web = json.loads(payload)
        return SearchAnswer(matches=tuple(parse_web_detection(web)), payload=payload)

    def search(self, images: Sequence[bytes]) -> list[SearchAnswer]:
        if not self._key:
            raise MissingApiKey
        results: list[SearchAnswer] = []
        for start in range(0, len(images), self.batch_size):
            chunk = images[start : start + self.batch_size]
            response = self._client.post(
                self._endpoint,
                params={"key": self._key},
                json={
                    "requests": [
                        {
                            "image": {"content": base64.b64encode(shrink(image)).decode()},
                            "features": [{"type": "WEB_DETECTION", "maxResults": 50}],
                        }
                        for image in chunk
                    ]
                },
            )
            response.raise_for_status()
            for item in response.json().get("responses", []):
                if "error" in item:
                    raise RuntimeError(item["error"].get("message", "Vision API error"))
                results.append(self.parse(json.dumps(item.get("webDetection", {}))))
        return results
