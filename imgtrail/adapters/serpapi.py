"""Google Lens through SerpApi: a second index, not a better one.

Vision and Lens disagree about where a photo is. Measured on one photograph: Vision found
it on nine Facebook pages and never mentioned Pinterest; Lens found it on three Pinterest
boards and a Facebook group Vision missed. Neither is a superset, so both are kept.

Images are uploaded, not linked. A tool for finding where your private photographs leaked
has no business publishing them to a URL first.
"""

from __future__ import annotations

import io
import json
from collections.abc import Sequence
from typing import Any

import httpx
from PIL import Image

from imgtrail.domain import Match, MatchKind, SearchAnswer

UPLOAD_ENDPOINT = "https://serpapi.com/image"
SEARCH_ENDPOINT = "https://serpapi.com/search"
PRICE_PER_1K = 15.0
"""Developer plan: $75/month for 5000. A subscription, so this prices a run, not a bill."""
FREE_UNITS_PER_MONTH = 250
MAX_UPLOAD_BYTES = 500 * 1024


def shrink(image: bytes, limit: int = MAX_UPLOAD_BYTES) -> bytes:
    """Under SerpApi's upload limit, which the 1280px of the Vision path is not."""
    for side in (1024, 800, 640, 480):
        with Image.open(io.BytesIO(image)) as opened:
            converted = opened.convert("RGB")
            converted.thumbnail((side, side))
            buffer = io.BytesIO()
            converted.save(buffer, format="JPEG", quality=85)
            if buffer.tell() <= limit:
                break
    return buffer.getvalue()


def parse_visual_matches(body: dict[str, Any]) -> list[Match]:
    """`visual_matches` pairs a page with the image on it — the same shape Vision answers in.

    `thumbnail` is Google's own cache of your photo and is not a place it ended up; reading
    it instead of `image` is how this adapter's first draft "found" five copies on
    gstatic.com. `image` is the picture as the source site serves it, and the only field
    worth downloading.

    Every match is PARTIAL: Lens does not say whether it matched the whole frame, and
    claiming otherwise would poison the one signal that separates a real hit from noise.
    """
    matches: list[Match] = []
    seen: set[tuple[str | None, str]] = set()
    for entry in body.get("visual_matches", []):
        image_url, page = entry.get("image"), entry.get("link")
        if not image_url or (page, image_url) in seen:
            continue
        seen.add((page, image_url))
        matches.append(
            Match(
                kind=MatchKind.PARTIAL,
                image_url=image_url,
                page_url=page,
                title=entry.get("title"),
            )
        )
    return matches


class MissingApiKey(RuntimeError):
    """Planning a scan is free; running one is not."""


class LensSearchEngine:
    name = "google-lens"
    batch_size = 1  # one upload and one search per photo; there is no batch endpoint
    free_units_per_month = FREE_UNITS_PER_MONTH
    price_per_1k = PRICE_PER_1K

    def __init__(
        self,
        api_key: str = "",
        timeout: float = 90.0,
        client: httpx.Client | None = None,
        upload_endpoint: str = UPLOAD_ENDPOINT,
        search_endpoint: str = SEARCH_ENDPOINT,
    ) -> None:
        self._key = api_key
        self._upload = upload_endpoint
        self._search = search_endpoint
        self._client = client or httpx.Client(timeout=timeout)

    def close(self) -> None:
        self._client.close()

    def estimated_cost(self, units: int, already_used: int = 0) -> float:
        billable = max(0, units + already_used - FREE_UNITS_PER_MONTH)
        return round(billable * PRICE_PER_1K / 1000, 2)

    def parse(self, payload: str) -> SearchAnswer:
        return SearchAnswer(
            matches=tuple(parse_visual_matches(json.loads(payload))), payload=payload
        )

    def search(self, images: Sequence[bytes]) -> list[SearchAnswer]:
        if not self._key:
            raise MissingApiKey
        answers = []
        for image in images:
            uploaded = self._client.post(
                self._upload,
                params={"api_key": self._key},
                files={"image": ("photo.jpg", shrink(image), "image/jpeg")},
            )
            uploaded.raise_for_status()
            found = self._client.get(
                self._search,
                params={
                    "engine": "google_lens",
                    "image_id": uploaded.json()["image_id"],
                    "api_key": self._key,
                },
            )
            found.raise_for_status()
            body = found.json()
            if body.get("error"):
                raise RuntimeError(str(body["error"]))
            answers.append(self.parse(json.dumps(body)))
        return answers
