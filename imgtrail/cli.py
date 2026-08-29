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
from .adapters.vision import FREE_UNITS_PER_MONTH, PRICE_PER_1K, VisionSearchEngine, explain
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


def _verify(service: ScanService, repository: SqliteRepository, workers: int) -> None:
    outstanding = len(repository.awaiting_verdict())
    if not outstanding:
        return
    with _progress() as bar:
        task = bar.add_task("Verifying", total=outstanding)
        tally = service.verify(workers, on_result=lambda: bar.advance(task))
    console.print(
        f"[green]{tally.get(Verdict.CONFIRMED, 0)}[/] confirmed · "
        f"[yellow]{tally.get(Verdict.LIKELY, 0)}[/] likely · "
        f"[dim]{tally.get(Verdict.REJECTED, 0)} rejected, "
        f"{tally.get(Verdict.UNREACHABLE, 0)} unreachable[/]"
    )


def cmd_scan(args: argparse.Namespace) -> int:
    data_dir = Path(args.data_dir)
    source = LocalPhotoSource(Path(args.source).expanduser(), data_dir)
    engine = VisionSearchEngine(_api_key(args.api_key))
    fetcher = HttpImageFetcher()

    with _repository(data_dir) as repository:
        service = ScanService(repository, repository, engine, source, fetcher, repository)

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

        plan = service.plan(args.limit, again=args.again, under=source.prefix)
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
                f"{indexed.unique} unique photos searched; "
                f"{plan.spent_this_month} searches billed this month so far.[/]"
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
                _verify(service, repository, args.workers)
        finally:
            engine.close()
            fetcher.close()

    console.print(f"\nDone. Run [bold]imgtrail report --data-dir {data_dir}[/] for the report.")
    return 0


def cmd_reparse(args: argparse.Namespace) -> int:
    """Re-read the answers already paid for. The filters may have been wrong; the money
    was still spent, and this is what makes correcting them free."""
    data_dir = Path(args.data_dir)
    engine = VisionSearchEngine()
    fetcher = HttpImageFetcher()
    with _repository(data_dir) as repository:
        service = ScanService(
            repository, repository, engine, FileImageLoader(), fetcher, repository
        )
        try:
            recovered = service.reparse(OWN_PLATFORMS | frozenset(args.ignore_domain or []))
            answers = len(repository.all())
            console.print(
                f"[bold]{recovered}[/] candidates recovered from {answers} stored answers "
                f"[dim](no search, no cost)[/]"
            )
            if not args.no_verify:
                _verify(service, repository, args.workers)
        finally:
            engine.close()
            fetcher.close()
    console.print(f"\nDone. Run [bold]imgtrail --data-dir {data_dir} report[/] for the report.")
    return 0


def _short(url: str, width: int = 62) -> str:
    """A terminal is 80 columns and the scheme is never the interesting part."""
    bare = url.removeprefix("https://").removeprefix("http://")
    return bare if len(bare) <= width else f"{bare[: width - 1]}…"


def cmd_trace(args: argparse.Namespace) -> int:
    """Everything the engine said about one photo, and what became of each part of it.

    The report is a filtered opinion. This is the record behind it, so "why is my photo
    not in there" stops being a question you answer by reading the source."""
    with _repository(Path(args.data_dir)) as repository:
        found = repository.matching(args.photo)
        if not found:
            console.print(f"[red]No photo matching[/] {args.photo}")
            return 1
        if len(found) > 1:
            console.print(f"[yellow]{len(found)} photos match[/] {args.photo}:")
            for photo in found[:15]:
                console.print(f"   {photo.path}")
            if len(found) > 15:
                console.print(f"   [dim]…and {len(found) - 15} more[/]")
            return 1

        photo = found[0]
        group = photo.group_id or photo.id
        assert group is not None
        console.print(f"[bold]{photo.path}[/]")
        collapsed = "" if photo.id == group else f" [dim](collapsed into group {group})[/]"
        flat = " · [yellow]flat frame, never searched[/]" if photo.fingerprint.is_degenerate else ""
        console.print(f"  {photo.fingerprint} · group {group}{collapsed}{flat}")

        payload = repository.answer_for(group)
        if payload is None:
            console.print("\n[yellow]No archived answer[/] — not searched, or searched before")
            console.print("[dim]answers were kept. A scan --again would fetch one.[/]")
            return 0

        answer = explain(payload)
        judged = {(m.page_url, m.image_url): m for m in repository.matches_for(group)}
        named = list({(m.page_url, m.image_url): m for m in answer.matches}.values())
        dropped = [m for m in named if (m.page_url, m.image_url) not in judged]

        guess = f' — best guess "{answer.guess}"' if answer.guess else ""
        console.print(f"\n[bold]the engine answered[/]{guess}")
        console.print(f"  {len(named)} candidates with an image to check")
        if answer.unnamed_pages:
            console.print(
                f"  [dim]{len(answer.unnamed_pages)} pages named with no image — dropped, "
                f"topical: 9.6% of those claims held[/]"
            )
        if answer.similar:
            console.print(
                f"  [dim]{len(answer.similar)} visually similar — dropped, "
                f"likeness is not a copy[/]"
            )

        if judged:
            console.print("\n[bold]what became of them[/]")
            for match in judged.values():
                colour = "green" if match.verdict is Verdict.CONFIRMED else "dim"
                distance = f"d={match.distance}" if match.distance is not None else "—"
                console.print(
                    f"  [{colour}]{match.verdict.value:11}[/] {distance:5} {_short(match.target)}",
                    no_wrap=True,
                    overflow="ellipsis",
                )
        if dropped:
            console.print(f"\n[yellow]{len(dropped)} dropped before storing[/] (own platform)")
            for match in dropped[:10]:
                console.print(
                    f"  [dim]{match.domain:24} {_short(match.target)}[/]",
                    no_wrap=True,
                    overflow="ellipsis",
                )
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
        "--again",
        action="store_true",
        help="search every photo again, including ones already searched — you pay for them twice",
    )
    scan.add_argument(
        "--no-verify", action="store_true", help="skip downloading candidates to confirm them"
    )
    scan.add_argument(
        "--workers", type=int, default=8, help="parallel downloads during verification (default 8)"
    )
    scan.set_defaults(func=cmd_scan)

    reparse = sub.add_parser(
        "reparse", help="re-read the stored answers under today's filters, without searching"
    )
    reparse.add_argument(
        "--ignore-domain",
        action="append",
        metavar="DOMAIN",
        help="extra domain to exclude from results (repeatable)",
    )
    reparse.add_argument(
        "--no-verify", action="store_true", help="skip downloading candidates to confirm them"
    )
    reparse.add_argument(
        "--workers", type=int, default=8, help="parallel downloads during verification (default 8)"
    )
    reparse.set_defaults(func=cmd_reparse)

    trace = sub.add_parser(
        "trace", help="everything the engine said about one photo, and what became of it"
    )
    trace.add_argument("photo", help="part of the photo's filename or path")
    trace.set_defaults(func=cmd_trace)

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
