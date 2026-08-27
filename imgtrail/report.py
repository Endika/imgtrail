"""Self-contained HTML report (thumbnails inlined) plus a JSON dump."""

from __future__ import annotations

import base64
import html
import json
import sqlite3
from pathlib import Path

from .hashing import thumbnail_png

INTERESTING = ("confirmed", "likely")


def collect(conn: sqlite3.Connection, statuses: tuple[str, ...] = INTERESTING) -> list[dict]:
    placeholders = ",".join("?" * len(statuses))
    rows = conn.execute(
        f"""SELECT h.group_id, p.path, h.page_url, h.image_url, h.title,
                   h.kind, h.status, h.distance, h.domain
            FROM hits h JOIN photos p ON p.id = h.group_id
            WHERE h.status IN ({placeholders}) AND h.domain IS NOT NULL
            ORDER BY h.group_id, h.status, h.domain""",
        statuses,
    ).fetchall()

    sizes = {
        r["group_id"]: r["n"]
        for r in conn.execute(
            "SELECT group_id, COUNT(*) AS n FROM photos GROUP BY group_id")
    }

    grouped: dict[int, dict] = {}
    for row in rows:
        entry = grouped.setdefault(row["group_id"], {
            "group_id": row["group_id"],
            "path": row["path"],
            "copies": sizes.get(row["group_id"], 1),
            "hits": [],
        })
        entry["hits"].append({
            "domain": row["domain"],
            "page_url": row["page_url"],
            "image_url": row["image_url"],
            "title": row["title"],
            "kind": row["kind"],
            "status": row["status"],
            "distance": row["distance"],
        })
    return sorted(grouped.values(), key=lambda e: -len(e["hits"]))


def summary(conn: sqlite3.Connection) -> dict:
    counts = dict(conn.execute(
        "SELECT status, COUNT(*) FROM hits GROUP BY status").fetchall())
    return {
        "photos": conn.execute("SELECT COUNT(*) FROM photos").fetchone()[0],
        "groups": conn.execute(
            "SELECT COUNT(*) FROM photos WHERE id = group_id").fetchone()[0],
        "searched": conn.execute("SELECT COUNT(*) FROM searches").fetchone()[0],
        "hits": counts,
    }


def write_json(conn: sqlite3.Connection, out: Path) -> None:
    out.write_text(json.dumps(
        {"summary": summary(conn), "findings": collect(conn)}, indent=2, ensure_ascii=False))


def _thumb(path: str) -> str:
    try:
        return "data:image/png;base64," + base64.b64encode(thumbnail_png(path)).decode()
    except OSError:
        return ""


BADGE = {"confirmed": "ok", "likely": "warn"}

CSS = """
:root { --bg:#fbfbfa; --fg:#1a1a19; --muted:#6b6b68; --card:#fff; --line:#e5e4e0;
        --ok:#1a7f4b; --ok-bg:#e6f4ec; --warn:#8a5a00; --warn-bg:#fdf3e0; --accent:#c2410c; }
@media (prefers-color-scheme: dark) {
  :root { --bg:#141413; --fg:#eeeeec; --muted:#9a9a96; --card:#1e1e1c; --line:#33332f;
          --ok:#6ee7a8; --ok-bg:#12291d; --warn:#f0c674; --warn-bg:#2b2110; --accent:#fb923c; }
}
* { box-sizing:border-box; }
body { margin:0; padding:2.5rem 1.5rem; background:var(--bg); color:var(--fg);
       font:15px/1.55 -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; }
.wrap { max-width:900px; margin:0 auto; }
h1 { font-size:1.6rem; margin:0 0 .3rem; letter-spacing:-.02em; }
.sub { color:var(--muted); margin:0 0 2rem; }
.stats { display:flex; flex-wrap:wrap; gap:2rem; padding:1rem 1.25rem; margin-bottom:2rem;
         background:var(--card); border:1px solid var(--line); border-radius:10px; }
.stat b { display:block; font-size:1.5rem; letter-spacing:-.02em; }
.stat span { color:var(--muted); font-size:.8rem; text-transform:uppercase; letter-spacing:.06em; }
.card { display:flex; gap:1.25rem; padding:1.25rem; margin-bottom:1rem; background:var(--card);
        border:1px solid var(--line); border-radius:10px; }
.card img { width:120px; height:120px; object-fit:cover; border-radius:8px; flex:none; }
.card h2 { font-size:.95rem; margin:0 0 .1rem; }
.card .meta { color:var(--muted); font-size:.8rem; margin:0 0 .8rem; }
ul { list-style:none; margin:0; padding:0; }
li { padding:.45rem 0; border-top:1px solid var(--line); font-size:.9rem;
     display:flex; gap:.6rem; align-items:baseline; flex-wrap:wrap; }
a { color:var(--accent); text-decoration:none; word-break:break-all; }
a:hover { text-decoration:underline; }
.badge { font-size:.7rem; padding:.12rem .45rem; border-radius:99px; flex:none;
         text-transform:uppercase; letter-spacing:.05em; font-weight:600; }
.badge.ok { color:var(--ok); background:var(--ok-bg); }
.badge.warn { color:var(--warn); background:var(--warn-bg); }
.dom { font-weight:600; }
.empty { padding:3rem; text-align:center; color:var(--muted); background:var(--card);
         border:1px solid var(--line); border-radius:10px; }
"""


def write_html(conn: sqlite3.Connection, out: Path) -> None:
    findings, stats = collect(conn), summary(conn)
    e = html.escape

    cards = []
    for f in findings:
        items = []
        for h in f["hits"]:
            target = h["page_url"] or h["image_url"]
            label = h["title"] or target
            d = h["distance"]
            dist = f'<span class="meta">Δ{d}</span>' if d is not None else ""
            items.append(
                f'<li><span class="badge {BADGE[h["status"]]}">{e(h["status"])}</span>'
                f'<span class="dom">{e(h["domain"])}</span>'
                f'<a href="{e(target)}" target="_blank" rel="noreferrer">'
                f'{e(label[:110])}</a>{dist}</li>'
            )
        copies = f' · {f["copies"]} copies in your profile' if f["copies"] > 1 else ""
        cards.append(
            f'<div class="card"><img src="{_thumb(f["path"])}" alt="">'
            f'<div><h2>{e(Path(f["path"]).name)}</h2>'
            f'<p class="meta">{len(f["hits"])} coincidencias{e(copies)}</p>'
            f'<ul>{"".join(items)}</ul></div></div>'
        )

    body = "".join(cards) or (
        '<div class="empty">None of your photos turned up on another site.</div>')
    hits = stats["hits"]
    tiles = [
        ("Photos", stats["photos"]), ("Unique", stats["groups"]),
        ("Searched", stats["searched"]),
        ("Confirmed", hits.get("confirmed", 0)), ("Likely", hits.get("likely", 0)),
        ("Discarded", hits.get("rejected", 0) + hits.get("unreachable", 0)),
    ]
    stat_html = "".join(
        f'<div class="stat"><b>{v}</b><span>{e(k)}</span></div>' for k, v in tiles)

    out.write_text(
        f'<!doctype html><html lang="en"><head><meta charset="utf-8">'
        f'<meta name="viewport" content="width=device-width,initial-scale=1">'
        f'<title>imgtrail</title><style>{CSS}</style></head><body><div class="wrap">'
        f'<h1>Where did your photos end up?</h1>'
        f'<p class="sub">Verified matches outside Instagram.</p>'
        f'<div class="stats">{stat_html}</div>{body}</div></body></html>',
        encoding="utf-8",
    )
