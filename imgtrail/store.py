"""SQLite state. Everything is idempotent so a re-run never re-pays for a search."""

from __future__ import annotations

import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS photos (
    id       INTEGER PRIMARY KEY,
    path     TEXT NOT NULL UNIQUE,
    phash    TEXT NOT NULL,
    group_id INTEGER
);
CREATE INDEX IF NOT EXISTS photos_group ON photos(group_id);

CREATE TABLE IF NOT EXISTS searches (
    group_id INTEGER PRIMARY KEY,
    engine   TEXT NOT NULL,
    done_at  TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS hits (
    id        INTEGER PRIMARY KEY,
    group_id  INTEGER NOT NULL,
    page_url  TEXT,
    image_url TEXT,
    title     TEXT,
    kind      TEXT NOT NULL,
    domain    TEXT,
    status    TEXT NOT NULL DEFAULT 'pending',
    distance  INTEGER,
    UNIQUE(group_id, page_url, image_url)
);
CREATE INDEX IF NOT EXISTS hits_status ON hits(status);
"""


def connect(data_dir: Path) -> sqlite3.Connection:
    data_dir.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(data_dir / "rastro.db")
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def add_photo(conn: sqlite3.Connection, path: str, phash: str) -> None:
    conn.execute(
        "INSERT INTO photos(path, phash) VALUES (?, ?) ON CONFLICT(path) DO NOTHING",
        (path, phash),
    )


def add_hit(conn: sqlite3.Connection, group_id: int, **f) -> None:
    conn.execute(
        """INSERT INTO hits(group_id, page_url, image_url, title, kind, domain)
           VALUES (?, ?, ?, ?, ?, ?)
           ON CONFLICT(group_id, page_url, image_url) DO NOTHING""",
        (group_id, f.get("page_url"), f.get("image_url"), f.get("title"),
         f["kind"], f.get("domain")),
    )


def mark_searched(conn: sqlite3.Connection, group_id: int, engine: str) -> None:
    conn.execute(
        "INSERT INTO searches(group_id, engine) VALUES (?, ?) "
        "ON CONFLICT(group_id) DO NOTHING",
        (group_id, engine),
    )


def unsearched_groups(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute(
        """SELECT p.id, p.path, p.phash FROM photos p
           LEFT JOIN searches s ON s.group_id = p.id
           WHERE p.group_id = p.id AND s.group_id IS NULL
           ORDER BY p.id"""
    ).fetchall()


def pending_hits(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute(
        """SELECT h.id, h.image_url, p.phash FROM hits h
           JOIN photos p ON p.id = h.group_id
           WHERE h.status = 'pending' AND h.image_url IS NOT NULL"""
    ).fetchall()


def set_hit_status(conn: sqlite3.Connection, hit_id: int, status: str,
                   distance: int | None = None) -> None:
    conn.execute("UPDATE hits SET status = ?, distance = ? WHERE id = ?",
                 (status, distance, hit_id))
