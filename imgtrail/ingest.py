"""Read the Instagram export (or any folder of images) and group near-duplicates."""

from __future__ import annotations

import sqlite3
import zipfile
from collections.abc import Iterator
from pathlib import Path

from . import store
from .hashing import hamming, phash

EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".heic", ".bmp"}
# The export ships avatars and other people's content alongside your own posts.
SKIP_PARTS = {"profile", "other", "messages", "stories_activity", "avatars"}


def discover(source: Path, data_dir: Path) -> Iterator[Path]:
    if source.is_file() and source.suffix.lower() == ".zip":
        source = _extract(source, data_dir)
    for path in sorted(source.rglob("*")):
        if path.suffix.lower() not in EXTENSIONS:
            continue
        if SKIP_PARTS & {p.lower() for p in path.parts}:
            continue
        yield path


def _extract(archive: Path, data_dir: Path) -> Path:
    target = data_dir / "extracted"
    if not target.exists():
        with zipfile.ZipFile(archive) as zf:
            zf.extractall(target)
    return target


def index(conn: sqlite3.Connection, source: Path, data_dir: Path) -> int:
    known = {r["path"] for r in conn.execute("SELECT path FROM photos")}
    added = 0
    for path in discover(source, data_dir):
        key = str(path.resolve())
        if key in known:
            continue
        try:
            store.add_photo(conn, key, phash(str(path)))
        except OSError:
            continue  # unreadable / not really an image
        added += 1
    conn.commit()
    return added


def assign_groups(conn: sqlite3.Connection, threshold: int = 6) -> int:
    """Greedy grouping: each photo joins the first representative within `threshold`,
    otherwise becomes a representative itself. group_id == id means representative."""
    reps: list[tuple[int, str]] = []
    for row in conn.execute("SELECT id, phash FROM photos ORDER BY id"):
        match = next((rid for rid, h in reps if hamming(h, row["phash"]) <= threshold), None)
        if match is None:
            reps.append((row["id"], row["phash"]))
            match = row["id"]
        conn.execute("UPDATE photos SET group_id = ? WHERE id = ?", (match, row["id"]))
    conn.commit()
    return len(reps)
