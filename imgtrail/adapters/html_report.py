"""Renders a report as a self-contained HTML page, or as JSON."""

from __future__ import annotations

import base64
import html
import io
import json
from dataclasses import asdict
from pathlib import Path

from PIL import Image

from imgtrail.domain import Report, Verdict
from imgtrail.ports import ImageLoader

THUMBNAIL_PX = 160
BADGE_CLASS = {Verdict.CONFIRMED: "ok", Verdict.LIKELY: "warn"}

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
.card img { width:120px; height:120px; object-fit:cover; border-radius:8px; flex:none;
            background:var(--line); }
.card h2 { font-size:.95rem; margin:0 0 .1rem; }
.card .meta { color:var(--muted); font-size:.8rem; margin:0 0 .8rem; }
.card > div { min-width:0; flex:1; }
ul { list-style:none; margin:0; padding:0; }
li { padding:.45rem 0; border-top:1px solid var(--line); font-size:.9rem;
     display:flex; gap:.6rem; align-items:baseline; flex-wrap:wrap; }
a { color:var(--accent); text-decoration:none; word-break:break-all; }
a:hover { text-decoration:underline; }
.badge { font-size:.7rem; padding:.12rem .45rem; border-radius:99px; flex:none;
         text-transform:uppercase; letter-spacing:.05em; font-weight:600; }
.badge.ok { color:var(--ok); background:var(--ok-bg); }
.badge.warn { color:var(--warn); background:var(--warn-bg); }
.badge.lead { color:var(--muted); background:var(--line); }
h2.section { font-size:1.1rem; margin:2.5rem 0 .3rem; letter-spacing:-.01em; }
.dom { font-weight:600; }
.empty { padding:3rem; text-align:center; color:var(--muted); background:var(--card);
         border:1px solid var(--line); border-radius:10px; }
"""


class HtmlReportWriter:
    def __init__(self, loader: ImageLoader, thumbnail_px: int = THUMBNAIL_PX) -> None:
        self._loader = loader
        self._px = thumbnail_px

    def write(self, report: Report, destination: Path) -> None:
        destination.write_text(self._render(report), encoding="utf-8")

    def _thumbnail(self, reference: str) -> str:
        try:
            with Image.open(io.BytesIO(self._loader.load(reference))) as opened:
                converted = opened.convert("RGB")
                converted.thumbnail((self._px, self._px))
                buffer = io.BytesIO()
                # JPEG, not PNG: these are photographs, and one card per lead means a
                # hundred of them on a page. PNG made that report 3.4 MB.
                converted.save(buffer, format="JPEG", quality=80, optimize=True)
        except (OSError, ValueError):
            return ""
        return "data:image/jpeg;base64," + base64.b64encode(buffer.getvalue()).decode()

    def _render(self, report: Report) -> str:
        escape = html.escape
        cards = []
        for finding in report.findings:
            items = []
            for match in finding.matches:
                distance = (
                    f'<span class="meta">&#916;{match.distance}</span>'
                    if match.distance is not None
                    else ""
                )
                label = escape((match.title or match.target)[:110])
                items.append(
                    f'<li><span class="badge {BADGE_CLASS[match.verdict]}">'
                    f"{escape(match.verdict.value)}</span>"
                    f'<span class="dom">{escape(match.domain or "")}</span>'
                    f'<a href="{escape(match.target)}" target="_blank" rel="noreferrer">'
                    f"{label}</a>{distance}</li>"
                )
            copies = (
                f" &middot; {finding.copies} copies in your profile" if finding.copies > 1 else ""
            )
            cards.append(
                f'<div class="card"><img src="{self._thumbnail(finding.photo.path)}" alt="">'
                f"<div><h2>{escape(Path(finding.photo.path).name)}</h2>"
                f'<p class="meta">{len(finding.matches)} matches{copies}</p>'
                f"<ul>{''.join(items)}</ul></div></div>"
            )

        body = "".join(cards) or (
            '<div class="empty">None of your photos turned up on another site.</div>'
        )

        traces = []
        for entry in report.unverified:
            items = [
                f'<li><span class="badge lead">unreachable</span>'
                f'<span class="dom">{escape(lead.domain or "")}</span>'
                f'<a href="{escape(lead.page_url)}" target="_blank" rel="noreferrer">'
                f"{escape((lead.title or lead.page_url)[:110])}</a></li>"
                for lead in entry.leads
            ]
            traces.append(
                f'<div class="card"><img src="{self._thumbnail(entry.photo.path)}" alt="">'
                f"<div><h2>{escape(Path(entry.photo.path).name)}</h2>"
                f'<p class="meta">{len(entry.leads)} places that could not be checked</p>'
                f"<ul>{''.join(items)}</ul></div></div>"
            )
        if traces:
            body += (
                '<h2 class="section">Found, but not verified</h2>'
                '<p class="sub">The search named an image on these pages and the site would '
                "not serve it, so nothing could be compared. Places to look with your own "
                "eyes — not findings.</p>" + "".join(traces)
            )

        summary, tally = report.summary, report.summary.tally
        tiles = [
            ("Photos", summary.photos),
            ("Unique", summary.unique),
            ("Searched", summary.searched),
            ("Confirmed", tally.get(Verdict.CONFIRMED, 0)),
            ("Likely", tally.get(Verdict.LIKELY, 0)),
            ("Unverified", sum(len(e.leads) for e in report.unverified)),
            ("Discarded", tally.get(Verdict.REJECTED, 0)),
        ]
        stats = "".join(f'<div class="stat"><b>{v}</b><span>{k}</span></div>' for k, v in tiles)

        return (
            '<!doctype html><html lang="en"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<title>imgtrail</title><style>{CSS}</style></head><body><div class="wrap">'
            "<h1>Where did your photos end up?</h1>"
            '<p class="sub">Verified matches outside Instagram.</p>'
            f'<div class="stats">{stats}</div>{body}</div></body></html>'
        )


class JsonReportWriter:
    def write(self, report: Report, destination: Path) -> None:
        payload = {
            "summary": {
                "photos": report.summary.photos,
                "unique": report.summary.unique,
                "searched": report.summary.searched,
                "tally": {v.value: n for v, n in report.summary.tally.items()},
            },
            "unverified": [
                {
                    "photo": entry.photo.path,
                    "leads": [
                        {
                            "page_url": lead.page_url,
                            "title": lead.title,
                            "domain": lead.domain,
                        }
                        for lead in entry.leads
                    ],
                }
                for entry in report.unverified
            ],
            "findings": [
                {
                    "photo": finding.photo.path,
                    "copies": finding.copies,
                    "matches": [
                        {
                            **asdict(m),
                            "kind": m.kind.value,
                            "verdict": m.verdict.value,
                            "domain": m.domain,
                        }
                        for m in finding.matches
                    ],
                }
                for finding in report.findings
            ],
        }
        destination.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
