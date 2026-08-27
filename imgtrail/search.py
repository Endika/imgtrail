"""Reverse image search backends.

Only Google Cloud Vision `WEB_DETECTION` in v1, behind a tiny protocol so TinEye or
Yandex can be added without touching the rest of the pipeline.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass
from typing import Protocol
from urllib.parse import urlparse

import httpx

from .hashing import encode_for_api

ENDPOINT = "https://vision.googleapis.com/v1/images:annotate"
BATCH_SIZE = 16  # Vision's per-request cap
PRICE_PER_1K = 3.50
FREE_UNITS_PER_MONTH = 1000

# Where your own photos obviously live. Reporting these as "found elsewhere" is noise.
DEFAULT_IGNORED = {
    "instagram.com", "cdninstagram.com", "facebook.com", "fbcdn.net",
    "threads.net", "threads.com", "whatsapp.com", "messenger.com",
}


@dataclass(frozen=True)
class Hit:
    kind: str  # "full" | "partial"
    page_url: str | None = None
    image_url: str | None = None
    title: str | None = None

    @property
    def domain(self) -> str | None:
        target = self.page_url or self.image_url
        if not target:
            return None
        host = urlparse(target).hostname or ""
        return host.removeprefix("www.").lower() or None


class Engine(Protocol):
    name: str

    def search(self, paths: list[str]) -> list[list[Hit]]: ...


def is_ignored(domain: str | None, ignored: set[str]) -> bool:
    if not domain:
        return False
    return any(domain == d or domain.endswith("." + d) for d in ignored)


class VisionEngine:
    name = "google-vision"

    def __init__(self, api_key: str, timeout: float = 60.0):
        self._key = api_key
        self._client = httpx.Client(timeout=timeout)

    def close(self) -> None:
        self._client.close()

    def search(self, paths: list[str]) -> list[list[Hit]]:
        """One request per batch of <=16 images; results come back in request order."""
        results: list[list[Hit]] = []
        for start in range(0, len(paths), BATCH_SIZE):
            chunk = paths[start:start + BATCH_SIZE]
            payload = {"requests": [
                {
                    "image": {"content": base64.b64encode(encode_for_api(p)).decode()},
                    "features": [{"type": "WEB_DETECTION", "maxResults": 50}],
                }
                for p in chunk
            ]}
            response = self._client.post(ENDPOINT, params={"key": self._key}, json=payload)
            response.raise_for_status()
            for item in response.json().get("responses", []):
                if "error" in item:
                    raise RuntimeError(item["error"].get("message", "Vision API error"))
                results.append(parse_web_detection(item.get("webDetection", {})))
        return results


def parse_web_detection(web: dict) -> list[Hit]:
    """Flatten Vision's response into hits.

    `pagesWithMatchingImages` is the useful part — it pairs a page with the image on it.
    Top-level `fullMatchingImages` catches hosted copies Google never tied to a page.
    `visuallySimilarImages` is deliberately dropped: it is semantic similarity, not
    "this is your photo", and it swamps the report with false positives.
    """
    hits: list[Hit] = []
    seen: set[tuple[str | None, str | None]] = set()

    def push(kind: str, page_url: str | None, image_url: str | None, title: str | None):
        key = (page_url, image_url)
        if key != (None, None) and key not in seen:
            seen.add(key)
            hits.append(Hit(kind=kind, page_url=page_url, image_url=image_url, title=title))

    for page in web.get("pagesWithMatchingImages", []):
        page_url, title = page.get("url"), page.get("pageTitle")
        images = [(i.get("url"), "full") for i in page.get("fullMatchingImages", [])]
        images += [(i.get("url"), "partial") for i in page.get("partialMatchingImages", [])]
        if not images:
            push("partial", page_url, None, title)
        for image_url, kind in images:
            push(kind, page_url, image_url, title)

    for image in web.get("fullMatchingImages", []):
        push("full", None, image.get("url"), None)

    return hits


def estimate_cost(units: int, already_used: int = 0) -> float:
    billable = max(0, units + already_used - FREE_UNITS_PER_MONTH)
    return round(billable * PRICE_PER_1K / 1000, 2)
