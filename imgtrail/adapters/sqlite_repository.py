"""SQLite persistence. The only file in the project that knows SQL exists.

Writes commit immediately: at album scale the cost is invisible, and it means an
interrupted run never loses a search that has already been paid for.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Sequence
from pathlib import Path

from imgtrail.domain import Fingerprint, Match, MatchKind, Photo, Summary, Verdict

SCHEMA = """
PRAGMA journal_mode = WAL;

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

CREATE TABLE IF NOT EXISTS responses (
    group_id INTEGER PRIMARY KEY,
    engine   TEXT NOT NULL,
    payload  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS matches (
    id        INTEGER PRIMARY KEY,
    group_id  INTEGER NOT NULL REFERENCES photos(id),
    page_url  TEXT,
    image_url TEXT,
    title     TEXT,
    kind      TEXT NOT NULL,
    domain    TEXT,
    verdict   TEXT NOT NULL DEFAULT 'pending',
    distance  INTEGER,
    UNIQUE(group_id, page_url, image_url)
);
CREATE INDEX IF NOT EXISTS matches_verdict ON matches(verdict);

-- Rows written before page-only hits were rejected. They carry no image, so they can
-- never be verified and can no longer be loaded as domain objects. Dropping them is
-- lossless: every one of them was noise by construction.
DELETE FROM matches WHERE image_url IS NULL OR image_url = '';
"""


def _to_match(row: sqlite3.Row) -> Match:
    return Match(
        id=row["id"],
        kind=MatchKind(row["kind"]),
        page_url=row["page_url"],
        image_url=row["image_url"],
        title=row["title"],
        verdict=Verdict(row["verdict"]),
        distance=row["distance"],
    )


class SqliteRepository:
    """Implements both PhotoRepository and MatchRepository over one database file."""

    def __init__(self, database: Path | str) -> None:
        if isinstance(database, Path):
            database.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(database, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> SqliteRepository:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # --- PhotoRepository -------------------------------------------------

    def add(self, photo: Photo) -> None:
        self._conn.execute(
            "INSERT INTO photos(path, phash) VALUES (?, ?) ON CONFLICT(path) DO NOTHING",
            (photo.path, photo.fingerprint.value),
        )
        self._conn.commit()

    def known_references(self) -> set[str]:
        return {row["path"] for row in self._conn.execute("SELECT path FROM photos")}

    def fingerprints(self) -> list[tuple[int, Fingerprint]]:
        return [
            (row["id"], Fingerprint(row["phash"]))
            for row in self._conn.execute("SELECT id, phash FROM photos ORDER BY id")
        ]

    def assign_groups(self, assignment: dict[int, int]) -> None:
        self._conn.executemany(
            "UPDATE photos SET group_id = ? WHERE id = ?",
            [(group, photo) for photo, group in assignment.items()],
        )
        self._conn.commit()

    def representatives_awaiting_search(self) -> list[Photo]:
        return [
            Photo(
                id=row["id"],
                path=row["path"],
                fingerprint=Fingerprint(row["phash"]),
                group_id=row["id"],
            )
            for row in self._conn.execute(
                """SELECT p.id, p.path, p.phash FROM photos p
                   LEFT JOIN searches s ON s.group_id = p.id
                   WHERE p.group_id = p.id AND s.group_id IS NULL
                   ORDER BY p.id"""
            )
        ]

    def representatives(self) -> list[Photo]:
        """Every group, searched or not — what `--again` asks for."""
        return [
            Photo(
                id=row["id"],
                path=row["path"],
                fingerprint=Fingerprint(row["phash"]),
                group_id=row["id"],
            )
            for row in self._conn.execute(
                "SELECT id, path, phash FROM photos WHERE group_id = id ORDER BY id"
            )
        ]

    def searched_this_month(self) -> int:
        """The free tier resets with the calendar month, so the all-time count misprices a run."""
        row = self._conn.execute(
            """SELECT COUNT(*) AS n FROM searches
               WHERE strftime('%Y-%m', done_at) = strftime('%Y-%m', 'now')"""
        ).fetchone()
        return int(row["n"])

    def mark_searched(self, group_id: int, engine: str) -> None:
        self._conn.execute(
            "INSERT INTO searches(group_id, engine) VALUES (?, ?) ON CONFLICT(group_id) DO NOTHING",
            (group_id, engine),
        )
        self._conn.commit()

    def counts(self) -> Summary:
        one = self._conn.execute(
            """SELECT (SELECT COUNT(*) FROM photos) AS photos,
                      (SELECT COUNT(*) FROM photos WHERE id = group_id) AS unique_photos,
                      (SELECT COUNT(*) FROM searches) AS searched"""
        ).fetchone()
        return Summary(
            photos=one["photos"], unique=one["unique_photos"], searched=one["searched"], tally={}
        )

    def by_ids(self, ids: Sequence[int]) -> dict[int, Photo]:
        if not ids:
            return {}
        holes = ",".join("?" * len(ids))
        return {
            row["id"]: Photo(
                id=row["id"],
                path=row["path"],
                fingerprint=Fingerprint(row["phash"]),
                group_id=row["group_id"],
            )
            for row in self._conn.execute(
                f"SELECT id, path, phash, group_id FROM photos WHERE id IN ({holes})", ids
            )
        }

    def group_sizes(self) -> dict[int, int]:
        return {
            row["group_id"]: row["n"]
            for row in self._conn.execute(
                "SELECT group_id, COUNT(*) AS n FROM photos GROUP BY group_id"
            )
        }

    # --- ResponseArchive --------------------------------------------------

    def save(self, group_id: int, engine: str, payload: str) -> None:
        self._conn.execute(
            """INSERT INTO responses(group_id, engine, payload) VALUES (?, ?, ?)
               ON CONFLICT(group_id) DO UPDATE SET engine = excluded.engine,
                                                   payload = excluded.payload""",
            (group_id, engine, payload),
        )
        self._conn.commit()

    def all(self) -> list[tuple[int, str]]:
        return [
            (row["group_id"], row["payload"])
            for row in self._conn.execute(
                "SELECT group_id, payload FROM responses ORDER BY group_id"
            )
        ]

    # --- MatchRepository -------------------------------------------------

    def add_all(self, group_id: int, matches: Sequence[Match]) -> int:
        before = self._conn.total_changes
        self._conn.executemany(
            """INSERT INTO matches(group_id, page_url, image_url, title, kind, domain)
               VALUES (?, ?, ?, ?, ?, ?)
               ON CONFLICT(group_id, page_url, image_url) DO NOTHING""",
            [(group_id, m.page_url, m.image_url, m.title, m.kind.value, m.domain) for m in matches],
        )
        self._conn.commit()
        return self._conn.total_changes - before

    def awaiting_verdict(self) -> list[tuple[Match, Fingerprint]]:
        return [
            (_to_match(row), Fingerprint(row["phash"]))
            for row in self._conn.execute(
                """SELECT m.*, p.phash FROM matches m
                   JOIN photos p ON p.id = m.group_id
                   WHERE m.verdict = ?""",
                (Verdict.PENDING.value,),
            )
        ]

    def record(self, match: Match) -> None:
        self._conn.execute(
            "UPDATE matches SET verdict = ?, distance = ? WHERE id = ?",
            (match.verdict.value, match.distance, match.id),
        )
        self._conn.commit()

    def findings(self, verdicts: Sequence[Verdict]) -> list[tuple[int, Match]]:
        holes = ",".join("?" * len(verdicts))
        return [
            (row["group_id"], _to_match(row))
            for row in self._conn.execute(
                f"""SELECT * FROM matches
                    WHERE verdict IN ({holes}) AND domain IS NOT NULL
                    ORDER BY group_id, verdict, domain""",
                [v.value for v in verdicts],
            )
        ]

    def tally(self) -> dict[Verdict, int]:
        return {
            Verdict(row["verdict"]): row["n"]
            for row in self._conn.execute(
                "SELECT verdict, COUNT(*) AS n FROM matches GROUP BY verdict"
            )
        }
