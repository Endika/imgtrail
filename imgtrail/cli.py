"""Composition root: parses arguments, builds the concrete adapters, wires the services.

This is the only module allowed to know every layer at once.
"""

from __future__ import annotations

import argparse
import os
import sys
import webbrowser
from pathlib import Path

from rich.console import Console
from rich.progress import BarColumn, Progress, TextColumn, TimeRemainingColumn

from .adapters.html_report import HtmlReportWriter, JsonReportWriter
from .adapters.http_fetcher import HttpImageFetcher
from .adapters.local_files import FileImageLoader, LocalPhotoSource
from .adapters.sqlite_repository import SqliteRepository
from .adapters.vision import FREE_UNITS_PER_MONTH, PRICE_PER_1K, VisionSearchEngine
from .domain import OWN_PLATFORMS, Verdict
from .services import IndexResult, ReportService, ScanService

console = Console()

API_KEY_HELP = (
    "[red]No API key.[/] Pass --api-key or export IMGTRAIL_API_KEY.\n"
    "Create one at console.cloud.google.com → APIs & Services → Credentials, "
    "with the Cloud Vision API enabled."
)


def _api_key(explicit: str | None) -> str:
    return explicit or os.environ.get("IMGTRAIL_API_KEY") or os.environ.get("GOOGLE_API_KEY") or ""


def _repository(data_dir: Path) -> SqliteRepository:
    return SqliteRepository(data_dir / "imgtrail.db")


def _progress() -> Progress:
    return Progress(
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TextColumn("{task.completed}/{task.total}"),
        TimeRemainingColumn(),
        console=console,
    )


def _source_tally(source: LocalPhotoSource, indexed: IndexResult) -> str:
    """Every picture the source saw, and where the ones that did not make it went.

    Without this line a skipped folder is invisible: the run reports the photos it kept
    and nothing at all about the ones it never looked at."""
    skipped = sum(source.skipped.values())
    parts = [f"[bold]{source.taken + skipped}[/] images in the source"]
    if skipped:
        where = ", ".join(f"{n} in {folder}" for folder, n in sorted(source.skipped.items()))
        parts.append(f"[yellow]{skipped} skipped[/] ({where})")
    if indexed.unreadable:
        parts.append(f"[yellow]{indexed.unreadable} unreadable[/]")
    return " · ".join(parts)


def cmd_scan(args: argparse.Namespace) -> int:
    data_dir = Path(args.data_dir)
    source = LocalPhotoSource(Path(args.source).expanduser(), data_dir)
    engine = VisionSearchEngine(_api_key(args.api_key))
    fetcher = HttpImageFetcher()

    with _repository(data_dir) as repository:
        service = ScanService(repository, repository, engine, source, fetcher)

        indexed = service.index(source, args.threshold)
        if indexed.total == 0:
            console.print(f"[red]No images found in {args.source}.")
            return 1
        console.print(_source_tally(source, indexed))
        console.print(
            f"[bold]{indexed.total}[/] photos ([green]+{indexed.added}[/] new) → "
            f"[bold]{indexed.unique}[/] unique after dedupe "
            f"([dim]{indexed.duplicates_saved} duplicate searches saved[/])"
        )

        plan = service.plan(args.limit)
        if plan.flat:
            left_out = "photo" if plan.flat == 1 else "photos"
            console.print(
                f"[yellow]{plan.flat} flat {left_out} left out[/][dim]: nothing to fingerprint, "
                f"and a flat frame matches every other flat frame online.[/]"
            )
        if args.dry_run:
            console.print(
                f"[yellow]dry-run[/]: would run [bold]{len(plan)}[/] searches on "
                f"{plan.engine_name}. Estimated cost [bold]${plan.cost}[/] "
                f"({FREE_UNITS_PER_MONTH} free per month, then ${PRICE_PER_1K}/1000)."
            )
            console.print(
                f"[dim]that would leave {plan.already_searched + len(plan)} of "
                f"{indexed.unique} unique photos searched.[/]"
            )
            return 0

        if len(plan) and not _api_key(args.api_key):
            console.print(API_KEY_HELP)
            return 2

        try:
            if len(plan):
                platforms = OWN_PLATFORMS | frozenset(args.ignore_domain or [])
                with _progress() as bar:
                    task = bar.add_task("Searching", total=len(plan))
                    service.search(plan, platforms, on_batch=lambda n: bar.advance(task, n))
            else:
                console.print("[dim]Nothing new to search.[/]")
            searched = repository.counts()
            console.print(
                f"[bold]{searched.searched}[/] of [bold]{searched.unique}[/] "
                f"unique photos searched on {plan.engine_name}"
            )

            if not args.no_verify:
                outstanding = len(repository.awaiting_verdict())
                if outstanding:
                    with _progress() as bar:
                        task = bar.add_task("Verifying", total=outstanding)
                        tally = service.verify(args.workers, on_result=lambda: bar.advance(task))
                    console.print(
                        f"[green]{tally.get(Verdict.CONFIRMED, 0)}[/] confirmed · "
                        f"[yellow]{tally.get(Verdict.LIKELY, 0)}[/] likely · "
                        f"[dim]{tally.get(Verdict.REJECTED, 0)} rejected, "
                        f"{tally.get(Verdict.UNREACHABLE, 0)} unreachable[/]"
                    )
        finally:
            engine.close()
            fetcher.close()

    console.print(f"\nDone. Run [bold]imgtrail report --data-dir {data_dir}[/] for the report.")
    return 0


def cmd_report(args: argparse.Namespace) -> int:
    data_dir = Path(args.data_dir)
    with _repository(data_dir) as repository:
        report = ReportService(repository, repository).build()
        destination = Path(args.out)
        HtmlReportWriter(FileImageLoader()).write(report, destination)
        console.print(f"Report → [bold]{destination.resolve()}[/]")
        if args.json:
            JsonReportWriter().write(report, Path(args.json))
            console.print(f"JSON   → [bold]{Path(args.json).resolve()}[/]")
    if args.open:
        webbrowser.open(destination.resolve().as_uri())
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    with _repository(Path(args.data_dir)) as repository:
        counts = repository.counts()
        tally = repository.tally()
    breakdown = ", ".join(f"{n} {verdict.value}" for verdict, n in sorted(tally.items()))
    console.print(
        f"{counts.photos} photos · {counts.unique} unique · {counts.searched} searched\n"
        f"matches: {breakdown or '—'}"
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="imgtrail", description="Find out where else on the web your Instagram photos show up."
    )
    parser.add_argument(
        "--data-dir",
        default="./imgtrail-data",
        help="where to keep the database and the extracted archive",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    scan = sub.add_parser("scan", help="index, dedupe, search and verify")
    scan.add_argument("source", help="Instagram data export (.zip) or a folder of images")
    scan.add_argument("--api-key", help="Cloud Vision API key")
    scan.add_argument("--limit", type=int, help="search at most N unique photos")
    scan.add_argument(
        "--dry-run",
        action="store_true",
        help="report how many searches and what they'd cost, without calling",
    )
    scan.add_argument(
        "--threshold",
        type=int,
        default=6,
        help="pHash distance below which two photos count as the same (default 6)",
    )
    scan.add_argument(
        "--ignore-domain",
        action="append",
        metavar="DOMAIN",
        help="extra domain to exclude from results (repeatable)",
    )
    scan.add_argument(
        "--no-verify", action="store_true", help="skip downloading candidates to confirm them"
    )
    scan.add_argument(
        "--workers", type=int, default=8, help="parallel downloads during verification (default 8)"
    )
    scan.set_defaults(func=cmd_scan)

    report = sub.add_parser("report", help="build the HTML report")
    report.add_argument("--out", default="imgtrail.html")
    report.add_argument("--json", metavar="FILE", help="also dump findings as JSON")
    report.add_argument("--open", action="store_true", help="open it in the browser")
    report.set_defaults(func=cmd_report)

    status = sub.add_parser("status", help="summary of what is in the database")
    status.set_defaults(func=cmd_status)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    exit_code: int = args.func(args)
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
