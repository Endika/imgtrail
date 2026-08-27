"""Second opinion on every hit.

Search engines return plenty of near-misses. Downloading the candidate and comparing
perceptual hashes is what turns a pile of URLs into something you can trust.
"""

from __future__ import annotations

import sqlite3
from concurrent.futures import ThreadPoolExecutor, as_completed

import httpx

from . import store
from .hashing import hamming, phash

CONFIRMED_MAX = 8   # same image, maybe recompressed
LIKELY_MAX = 16     # cropped, filtered or heavily edited
MAX_BYTES = 25 * 1024 * 1024
USER_AGENT = "Mozilla/5.0 (compatible; imgtrail/0.1; +reverse-image-verification)"


def classify(distance: int) -> str:
    if distance <= CONFIRMED_MAX:
        return "confirmed"
    if distance <= LIKELY_MAX:
        return "likely"
    return "rejected"


def _check(client: httpx.Client, url: str, original: str) -> tuple[str, int | None]:
    try:
        response = client.get(url, follow_redirects=True)
        response.raise_for_status()
        if not response.headers.get("content-type", "").startswith("image/"):
            return "unreachable", None
        if len(response.content) > MAX_BYTES:
            return "unreachable", None
        distance = hamming(original, phash(response.content))
    except (httpx.HTTPError, OSError, ValueError):
        return "unreachable", None
    return classify(distance), distance


def verify_pending(conn: sqlite3.Connection, workers: int = 8, progress=None) -> dict[str, int]:
    rows = store.pending_hits(conn)
    counts: dict[str, int] = {}
    if not rows:
        return counts

    with (
        httpx.Client(timeout=20.0, headers={"User-Agent": USER_AGENT}) as client,
        ThreadPoolExecutor(max_workers=workers) as pool,
    ):
        futures = {
            pool.submit(_check, client, row["image_url"], row["phash"]): row["id"]
            for row in rows
        }
        for future in as_completed(futures):
            status, distance = future.result()
            store.set_hit_status(conn, futures[future], status, distance)
            counts[status] = counts.get(status, 0) + 1
            if progress:
                progress()
    conn.commit()
    return counts
