"""End-to-end over the real pipeline with an in-memory search engine."""

from pathlib import Path

import pytest

from imgtrail import cli, ingest, report, store
from imgtrail.search import DEFAULT_IGNORED, Hit


class FakeEngine:
    """Answers with canned hits and records exactly which photos it was asked about."""

    name = "fake"

    def __init__(self, hits_by_path: dict[str, list[Hit]]):
        self._hits = hits_by_path
        self.asked: list[str] = []

    def search(self, paths: list[str]) -> list[list[Hit]]:
        self.asked.extend(paths)
        return [self._hits.get(Path(p).name, []) for p in paths]


@pytest.fixture
def indexed(photos: Path, tmp_path: Path):
    data = tmp_path / "data"
    conn = store.connect(data)
    ingest.index(conn, photos, data)
    ingest.assign_groups(conn)
    return conn


def test_a_full_run_stores_only_hits_outside_your_own_platforms(indexed):
    pending = store.unsearched_groups(indexed)
    engine = FakeEngine({
        Path(pending[0]["path"]).name: [
            Hit("full", "https://blog.example.com/p", "https://blog.example.com/i.jpg", "Blog"),
            Hit("full", "https://www.instagram.com/p/abc", None, "Instagram"),
            Hit("partial", "https://scontent.cdninstagram.com/i.jpg", None, None),
        ],
    })

    cli.run_searches(indexed, engine, pending, DEFAULT_IGNORED)

    domains = [r[0] for r in indexed.execute("SELECT domain FROM hits")]
    assert domains == ["blog.example.com"]


def test_duplicates_are_never_searched(indexed):
    pending = store.unsearched_groups(indexed)
    engine = FakeEngine({})

    cli.run_searches(indexed, engine, pending, DEFAULT_IGNORED)

    assert len(engine.asked) == 2, "3 photos, but two of them are the same picture"


def test_rerunning_costs_nothing(indexed):
    engine = FakeEngine({})
    cli.run_searches(indexed, engine, store.unsearched_groups(indexed), DEFAULT_IGNORED)

    second = FakeEngine({})
    cli.run_searches(indexed, second, store.unsearched_groups(indexed), DEFAULT_IGNORED)

    assert second.asked == []


def test_extra_ignored_domains_are_honoured(indexed):
    pending = store.unsearched_groups(indexed)
    engine = FakeEngine({
        Path(pending[0]["path"]).name: [
            Hit("full", "https://pinterest.com/pin/1", None, "Pin"),
            Hit("full", "https://blog.example.com/p", None, "Blog"),
        ],
    })

    cli.run_searches(indexed, engine, pending, DEFAULT_IGNORED | {"pinterest.com"})

    assert [r[0] for r in indexed.execute("SELECT domain FROM hits")] == ["blog.example.com"]


def test_the_report_shows_confirmed_hits_and_hides_rejected_ones(indexed, tmp_path: Path):
    pending = store.unsearched_groups(indexed)
    engine = FakeEngine({
        Path(pending[0]["path"]).name: [
            Hit("full", "https://good.example.com/p", "https://good.example.com/i.jpg", "Real"),
            Hit("full", "https://bad.example.com/p", "https://bad.example.com/i.jpg", "Wrong"),
        ],
    })
    cli.run_searches(indexed, engine, pending, DEFAULT_IGNORED)
    store.set_hit_status(indexed, 1, "confirmed", 2)
    store.set_hit_status(indexed, 2, "rejected", 30)
    indexed.commit()

    out = tmp_path / "report.html"
    report.write_html(indexed, out)
    html = out.read_text(encoding="utf-8")

    assert "good.example.com" in html
    assert "bad.example.com" not in html
    assert "data:image/png;base64," in html, "thumbnails must be inlined"


def test_report_is_readable_when_nothing_was_found(indexed, tmp_path: Path):
    out = tmp_path / "report.html"
    report.write_html(indexed, out)
    assert "None of your photos turned up" in out.read_text(encoding="utf-8")


def test_dry_run_prices_the_job_without_an_api_key(photos: Path, tmp_path: Path, capsys):
    code = cli.main([
        "--data-dir", str(tmp_path / "data"), "scan", str(photos), "--dry-run",
    ])

    out = capsys.readouterr().out
    assert code == 0
    assert "2" in out and "$0.0" in out
    assert not (tmp_path / "data" / "searches").exists()
