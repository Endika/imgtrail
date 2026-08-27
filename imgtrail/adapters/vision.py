"""Google Cloud Vision `WEB_DETECTION`, over plain REST with an API key.

Deliberately not the `google-cloud-vision` SDK: an API key is a two-minute setup, a
service account is not, and this endpoint is the only one we need.
"""

from __future__ import annotations

import base64
import io
from collections.abc import Sequence
from typing import Any

import httpx
from PIL import Image

from imgtrail.domain import Match, MatchKind

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
    Top-level `fullMatchingImages` catches hosted copies Google never tied to a page.
    `visuallySimilarImages` is dropped on purpose — it means "looks alike", not "is your
    photo", and it drowns the report in false positives.
    """
    matches: list[Match] = []
    seen: set[tuple[str | None, str | None]] = set()

    def push(kind: MatchKind, page: str | None, image: str | None, title: str | None) -> None:
        if (page or image) and (page, image) not in seen:
            seen.add((page, image))
            matches.append(Match(kind=kind, page_url=page, image_url=image, title=title))

    for page in web.get("pagesWithMatchingImages", []):
        url, title = page.get("url"), page.get("pageTitle")
        images = [(i.get("url"), MatchKind.FULL) for i in page.get("fullMatchingImages", [])]
        images += [(i.get("url"), MatchKind.PARTIAL) for i in page.get("partialMatchingImages", [])]
        if not images:
            push(MatchKind.PARTIAL, url, None, title)
        for image_url, kind in images:
            push(kind, url, image_url, title)

    for image in web.get("fullMatchingImages", []):
        push(MatchKind.FULL, None, image.get("url"), None)

    return matches


class MissingApiKey(RuntimeError):
    """Planning a scan is free; running one is not."""


class VisionSearchEngine:
    name = "google-vision"
    batch_size = 16  # Vision's per-request cap

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

    def search(self, images: Sequence[bytes]) -> list[list[Match]]:
        if not self._key:
            raise MissingApiKey
        results: list[list[Match]] = []
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
                results.append(parse_web_detection(item.get("webDetection", {})))
        return results
