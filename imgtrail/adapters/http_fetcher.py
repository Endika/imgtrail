"""Downloads candidate images so they can be checked against the original."""

from __future__ import annotations

from collections.abc import Mapping
from urllib.parse import urlparse

import httpx

MAX_BYTES = 25 * 1024 * 1024
USER_AGENT = "Mozilla/5.0 (compatible; imgtrail/0.1; +reverse-image-verification)"

CRAWLER_USER_AGENTS = {"lookaside.fbsbx.com": "facebookexternalhit/1.1"}
"""Hosts that hand over the picture to a crawler and to nobody else.

`lookaside.fbsbx.com/lookaside/crawler/media/` is how Facebook serves the image of a
public post; asked with any other agent it answers 396 bytes of HTML, and the copy goes
down as unverifiable. The path says `crawler`, so we knock as one — there and nowhere
else, which is why this is a mapping and not a blanket retry."""


class HttpImageFetcher:
    def __init__(
        self,
        timeout: float = 20.0,
        client: httpx.Client | None = None,
        crawler_hosts: Mapping[str, str] = CRAWLER_USER_AGENTS,
    ) -> None:
        self._crawler_hosts = crawler_hosts
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
        host = (urlparse(url).hostname or "").lower()
        crawler = self._crawler_hosts.get(host)
        try:
            response = self._client.get(url, headers={"User-Agent": crawler} if crawler else None)
            response.raise_for_status()
        except (httpx.HTTPError, httpx.InvalidURL, ValueError):
            # ValueError on purpose: httpx asks urllib to build the cookie header, and
            # urllib raises it on a scheme it does not know. One `x-raw-image://` row from
            # a search engine ended a run of 1123 verifications that way. A candidate we
            # cannot even ask for is a candidate we cannot check — nothing more than that.
            return None
        if not response.headers.get("content-type", "").startswith("image/"):
            return None
        if len(response.content) > MAX_BYTES:
            return None
        return response.content
