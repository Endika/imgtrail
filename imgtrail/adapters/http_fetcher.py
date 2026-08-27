"""Downloads candidate images so they can be checked against the original."""

from __future__ import annotations

import httpx

MAX_BYTES = 25 * 1024 * 1024
USER_AGENT = "Mozilla/5.0 (compatible; imgtrail/0.1; +reverse-image-verification)"


class HttpImageFetcher:
    def __init__(self, timeout: float = 20.0, client: httpx.Client | None = None) -> None:
        self._client = client or httpx.Client(
            timeout=timeout, headers={"User-Agent": USER_AGENT}, follow_redirects=True
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> HttpImageFetcher:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def fetch(self, url: str) -> bytes | None:
        """None whenever the URL does not yield an image we can compare."""
        try:
            response = self._client.get(url)
            response.raise_for_status()
        except httpx.HTTPError:
            return None
        if not response.headers.get("content-type", "").startswith("image/"):
            return None
        if len(response.content) > MAX_BYTES:
            return None
        return response.content
