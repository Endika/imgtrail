"""Command line entry point."""

from __future__ import annotations

import argparse
import os
import sys
import webbrowser
from pathlib import Path

from rich.console import Console
from rich.progress import BarColumn, Progress, TextColumn, TimeRemainingColumn

from . import ingest, report, search, store, verify
from .search import DEFAULT_IGNORED, VisionEngine, estimate_cost, is_ignored

console = Console()


def _api_key(args: argparse.Namespace) -> str:
    key = args.api_key or os.environ.get("IMGTRAIL_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not key:
        console.print(
            "[red]No API key.[/] Pass --api-key or export IMGTRAIL_API_KEY.\n"
            "Create one at console.cloud.google.com → APIs & Services → Credentials, "
            "with the Cloud Vision API enabled."
        )
        raise SystemExit(2)
    return key


def _progress() -> Progress:
    return Progress(
        TextColumn("[progress.description]{task.description}"),
        BarColumn(), TextColumn("{task.completed}/{task.total}"),
        TimeRemainingColumn(), console=console,
    )


def run_searches(conn, engine, pending, ignored, on_batch=None) -> int:
    """Search each unique photo, keeping only hits outside your own platforms.

    Commits per batch so an interrupted run never loses a search you already paid for.
    """
    stored = 0
    for start in range(0, len(pending), search.BATCH_SIZE):
        chunk = pending[start : start + search.BATCH_SIZE]
        for row, hits in zip(chunk, engine.search([r["path"] for r in chunk]), strict=True):
            for hit in hits:
                if is_ignored(hit.domain, ignored):
                    continue
                store.add_hit(conn, row["id"], page_url=hit.page_url,
                              image_url=hit.image_url, title=hit.title,
                              kind=hit.kind, domain=hit.domain)
                stored += 1
            store.mark_searched(conn, row["id"], engine.name)
        conn.commit()
        if on_batch:
            on_batch(len(chunk))
    return stored


def cmd_scan(args: argparse.Namespace) -> int:
    data_dir = Path(args.data_dir)
    conn = store.connect(data_dir)

    added = ingest.index(conn, Path(args.source).expanduser(), data_dir)
    groups_total = ingest.assign_groups(conn, args.threshold)
    total_photos = conn.execute("SELECT COUNT(*) FROM photos").fetchone()[0]
    if total_photos == 0:
        console.print(f"[red]No images found in {args.source}.")
        return 1
    console.print(
        f"[bold]{total_photos}[/] photos ([green]+{added}[/] new) → "
        f"[bold]{groups_total}[/] unique after dedupe "
        f"([dim]{total_photos - groups_total} duplicate searches saved[/])"
    )

    pending = store.unsearched_groups(conn)
    if args.limit:
        pending = pending[: args.limit]

    already = conn.execute("SELECT COUNT(*) FROM searches").fetchone()[0]
    if args.dry_run:
        console.print(
            f"[yellow]dry-run[/]: would run [bold]{len(pending)}[/] searches. "
            f"Estimated cost [bold]${estimate_cost(len(pending), already)}[/] "
            f"({search.FREE_UNITS_PER_MONTH} free per month, then "
            f"${search.PRICE_PER_1K}/1000)."
        )
        return 0

    ignored = DEFAULT_IGNORED | set(args.ignore_domain or [])
    if pending:
        engine = VisionEngine(_api_key(args))
        try:
            with _progress() as bar:
                task = bar.add_task("Searching", total=len(pending))
                run_searches(conn, engine, pending, ignored,
                             on_batch=lambda n: bar.advance(task, n))
        finally:
            engine.close()
    else:
        console.print("[dim]Nothing new to search.[/]")

    if not args.no_verify:
        rows = store.pending_hits(conn)
        if rows:
            with _progress() as bar:
                task = bar.add_task("Verifying", total=len(rows))
                counts = verify.verify_pending(
                    conn, args.workers, progress=lambda: bar.advance(task))
            console.print(
                f"[green]{counts.get('confirmed', 0)}[/] confirmed · "
                f"[yellow]{counts.get('likely', 0)}[/] likely · "
                f"[dim]{counts.get('rejected', 0)} rejected, "
                f"{counts.get('unreachable', 0)} unreachable[/]"
            )

    console.print(f"\nDone. Run [bold]imgtrail report --data-dir {data_dir}[/] for the report.")
    return 0


def cmd_report(args: argparse.Namespace) -> int:
    conn = store.connect(Path(args.data_dir))
    out = Path(args.out)
    report.write_html(conn, out)
    console.print(f"Report → [bold]{out.resolve()}[/]")
    if args.json:
        report.write_json(conn, Path(args.json))
        console.print(f"JSON   → [bold]{Path(args.json).resolve()}[/]")
    if args.open:
        webbrowser.open(out.resolve().as_uri())
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    conn = store.connect(Path(args.data_dir))
    stats = report.summary(conn)
    console.print(
        f"{stats['photos']} photos · {stats['groups']} unique · "
        f"{stats['searched']} searched\nhits: {stats['hits'] or '—'}"
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="imgtrail",
        description="Find out where else on the web your Instagram photos show up.")
    parser.add_argument("--data-dir", default="./imgtrail-data",
                        help="where to keep the database and the extracted archive")
    sub = parser.add_subparsers(dest="command", required=True)

    scan = sub.add_parser("scan", help="index, dedupe, search and verify")
    scan.add_argument("source", help="Instagram data export (.zip) or a folder of images")
    scan.add_argument("--api-key", help="Cloud Vision API key")
    scan.add_argument("--limit", type=int, help="search at most N unique photos")
    scan.add_argument("--dry-run", action="store_true",
                      help="report how many searches and what they'd cost, without calling")
    scan.add_argument("--threshold", type=int, default=6,
                      help="pHash distance below which two photos count as the same (default 6)")
    scan.add_argument("--ignore-domain", action="append", metavar="DOMAIN",
                      help="extra domain to exclude from results (repeatable)")
    scan.add_argument("--no-verify", action="store_true",
                      help="skip downloading candidates to confirm them")
    scan.add_argument("--workers", type=int, default=8,
                      help="parallel downloads during verification (default 8)")
    scan.set_defaults(func=cmd_scan)

    rep = sub.add_parser("report", help="build the HTML report")
    rep.add_argument("--out", default="imgtrail.html")
    rep.add_argument("--json", metavar="FILE", help="also dump findings as JSON")
    rep.add_argument("--open", action="store_true", help="open it in the browser")
    rep.set_defaults(func=cmd_report)

    st = sub.add_parser("status", help="summary of what is in the database")
    st.set_defaults(func=cmd_status)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
