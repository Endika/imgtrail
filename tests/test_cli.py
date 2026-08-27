"""The composition root, driven the way a user drives it."""

from __future__ import annotations

from pathlib import Path

import pytest

from imgtrail.cli import main

from .conftest import image_bytes, repost_bytes


@pytest.fixture
def album_dir(tmp_path: Path) -> Path:
    folder = tmp_path / "album"
    folder.mkdir()
    (folder / "a.png").write_bytes(image_bytes(1))
    (folder / "a_repost.jpg").write_bytes(repost_bytes(1))
    (folder / "b.png").write_bytes(image_bytes(99))
    return folder


def run(tmp_path: Path, *argv: str) -> int:
    return main(["--data-dir", str(tmp_path / "data"), *argv])


class TestScan:
    def test_dry_run_prices_the_job_without_a_key_or_a_request(
        self, album_dir: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        code = run(tmp_path, "scan", str(album_dir), "--dry-run")

        out = capsys.readouterr().out
        assert code == 0
        assert "2 unique" in out.replace("\n", " ")
        assert "$0.0" in out

    def test_a_real_scan_without_a_key_stops_before_spending(
        self,
        album_dir: Path,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.delenv("IMGTRAIL_API_KEY", raising=False)
        monkeypatch.delenv("GOOGLE_API_KEY", raising=False)

        code = run(tmp_path, "scan", str(album_dir))

        assert code == 2
        assert "No API key" in capsys.readouterr().out

    def test_an_empty_folder_is_an_error(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        empty = tmp_path / "empty"
        empty.mkdir()

        assert run(tmp_path, "scan", str(empty)) == 1
        assert "No images found" in capsys.readouterr().out

    def test_the_threshold_reaches_the_domain(
        self, album_dir: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        run(tmp_path, "scan", str(album_dir), "--dry-run", "--threshold", "0")

        assert "3 unique" in capsys.readouterr().out.replace("\n", " ")

    def test_a_limit_caps_what_would_be_searched(
        self, album_dir: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        run(tmp_path, "scan", str(album_dir), "--dry-run", "--limit", "1")

        assert "would run 1 searches" in capsys.readouterr().out.replace("\n", " ")

    def test_state_is_reused_across_invocations(
        self, album_dir: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        run(tmp_path, "scan", str(album_dir), "--dry-run")
        capsys.readouterr()

        run(tmp_path, "scan", str(album_dir), "--dry-run")

        assert "+0 new" in capsys.readouterr().out


class TestReportAndStatus:
    def test_report_writes_html_and_json(
        self, album_dir: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        run(tmp_path, "scan", str(album_dir), "--dry-run")
        html_out, json_out = tmp_path / "r.html", tmp_path / "r.json"

        code = run(tmp_path, "report", "--out", str(html_out), "--json", str(json_out))

        assert code == 0
        assert "None of your photos turned up" in html_out.read_text(encoding="utf-8")
        assert json_out.read_text(encoding="utf-8").startswith("{")

    def test_status_summarises_an_empty_database(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert run(tmp_path, "status") == 0
        assert "0 photos" in capsys.readouterr().out


class TestParser:
    def test_a_command_is_required(self) -> None:
        with pytest.raises(SystemExit):
            main([])

    def test_an_unknown_command_is_rejected(self) -> None:
        with pytest.raises(SystemExit):
            main(["nope"])
