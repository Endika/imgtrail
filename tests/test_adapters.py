"""Each adapter against the real thing it adapts: a real database, a real HTTP server."""

from __future__ import annotations

import functools
import http.server
import io
import json
import threading
import zipfile
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from PIL import Image

from imgtrail.adapters.html_report import HtmlReportWriter, JsonReportWriter
from imgtrail.adapters.http_fetcher import HttpImageFetcher
from imgtrail.adapters.local_files import FileImageLoader, LocalPhotoSource
from imgtrail.adapters.sqlite_repository import SqliteRepository
from imgtrail.adapters.vision import MissingApiKey, VisionSearchEngine, parse_web_detection, shrink
from imgtrail.domain import Fingerprint, Match, MatchKind, Report, Verdict
from imgtrail.ports import (
    ImageFetcher,
    ImageLoader,
    MatchRepository,
    PhotoRepository,
    PhotoSource,
    ReportWriter,
    SearchEngine,
)
from imgtrail.services import ReportService, ScanService

from .conftest import DictImageFetcher, DictPhotoSource, FakeSearchEngine, image_bytes


class TestPortConformance:
    """Cheap insurance that an adapter cannot drift away from its port unnoticed."""

    def test_every_adapter_satisfies_the_port_it_claims(self, tmp_path: Path) -> None:
        repository = SqliteRepository(":memory:")
        source = LocalPhotoSource(tmp_path, tmp_path)
        assert isinstance(repository, PhotoRepository)
        assert isinstance(repository, MatchRepository)
        assert isinstance(source, PhotoSource)
        assert isinstance(FileImageLoader(), ImageLoader)
        assert isinstance(VisionSearchEngine(), SearchEngine)
        assert isinstance(HttpImageFetcher(), ImageFetcher)
        assert isinstance(HtmlReportWriter(FileImageLoader()), ReportWriter)
        assert isinstance(JsonReportWriter(), ReportWriter)
        repository.close()


class TestSqliteRepository:
    def test_the_same_photo_is_never_stored_twice(self, repository: SqliteRepository) -> None:
        from imgtrail.domain import Photo

        photo = Photo(path="/a.png", fingerprint=Fingerprint("ff00ff00ff00ff00"))
        repository.add(photo)
        repository.add(photo)

        assert len(repository.fingerprints()) == 1

    def test_matches_are_deduplicated_per_group(self, repository: SqliteRepository) -> None:
        from imgtrail.domain import Photo

        repository.add(Photo(path="/a.png", fingerprint=Fingerprint("ff00ff00ff00ff00")))
        repository.assign_groups({1: 1})
        match = Match(MatchKind.FULL, page_url="https://ex.com/p", image_url="https://ex.com/i.jpg")

        assert repository.add_all(1, [match]) == 1
        assert repository.add_all(1, [match]) == 0

    def test_a_verdict_survives_a_round_trip(self, repository: SqliteRepository) -> None:
        from imgtrail.domain import Photo

        repository.add(Photo(path="/a.png", fingerprint=Fingerprint("ff00ff00ff00ff00")))
        repository.assign_groups({1: 1})
        repository.add_all(1, [Match(MatchKind.FULL, "https://ex.com/i.jpg", "https://ex.com/p")])
        pending, fingerprint = repository.awaiting_verdict()[0]

        repository.record(pending.judged(4))

        assert repository.tally() == {Verdict.CONFIRMED: 1}
        assert fingerprint == Fingerprint("ff00ff00ff00ff00")

    def test_legacy_page_only_rows_are_dropped_on_open(self, tmp_path: Path) -> None:
        """Databases written before page-only hits were rejected still hold them. They
        carry no image, so they can never become domain objects — opening must clear them."""
        import sqlite3

        database = tmp_path / "old.db"
        SqliteRepository(database).close()
        legacy = sqlite3.connect(database)
        legacy.execute("INSERT INTO photos(path, phash) VALUES ('/a.png', 'ff00ff00ff00ff00')")
        legacy.execute("UPDATE photos SET group_id = id")
        legacy.execute(
            "INSERT INTO matches(group_id, page_url, image_url, kind, domain, verdict) "
            "VALUES (1, 'https://noise.example/cumulus', NULL, 'partial', "
            "'noise.example', 'unreachable')"
        )
        legacy.commit()
        legacy.close()

        with SqliteRepository(database) as reopened:
            assert reopened.tally() == {}
            assert reopened.findings([Verdict.CONFIRMED, Verdict.LIKELY]) == []

    def test_state_survives_reopening_the_file(
        self, tmp_path: Path, album: DictPhotoSource
    ) -> None:
        from imgtrail.adapters.sqlite_repository import SqliteRepository as Store

        database = tmp_path / "state" / "imgtrail.db"
        with Store(database) as first:
            ScanService(first, first, FakeSearchEngine(), album, DictImageFetcher()).index(album)

        with Store(database) as second:
            assert second.counts().photos == 4


class TestVisionAdapter:
    RESPONSE = {
        "pagesWithMatchingImages": [
            {
                "url": "https://blog.example.com/post",
                "pageTitle": "Used my photo",
                "fullMatchingImages": [{"url": "https://cdn.example.com/mine.jpg"}],
            },
            {
                "url": "https://forum.example.org/thread",
                "partialMatchingImages": [{"url": "https://forum.example.org/crop.jpg"}],
            },
            {"url": "https://nolink.example.net/page", "pageTitle": "No image extracted"},
        ],
        "fullMatchingImages": [{"url": "https://cdn.example.com/mine.jpg"}],
        "visuallySimilarImages": [{"url": "https://unrelated.example.com/other.jpg"}],
    }

    def test_pages_images_and_kinds_are_parsed(self) -> None:
        matches = parse_web_detection(self.RESPONSE)

        assert (
            Match(
                MatchKind.FULL,
                "https://cdn.example.com/mine.jpg",
                "https://blog.example.com/post",
                "Used my photo",
            )
            in matches
        )
        assert any(m.kind is MatchKind.PARTIAL and m.domain == "forum.example.org" for m in matches)

    def test_a_page_with_no_extracted_image_is_dropped(self) -> None:
        """Vision lists pages it merely associates with the subject — a cloud photo comes
        back with pages about cumulus. Unfetchable, unverifiable, and almost always noise."""
        pages = {m.page_url for m in parse_web_detection(self.RESPONSE)}

        assert "https://nolink.example.net/page" not in pages

    def test_visually_similar_images_are_dropped(self) -> None:
        urls = {m.image_url for m in parse_web_detection(self.RESPONSE)}
        assert "https://unrelated.example.com/other.jpg" not in urls

    def test_the_same_pair_is_not_reported_twice(self) -> None:
        matches = parse_web_detection(self.RESPONSE)
        assert len({(m.page_url, m.image_url) for m in matches}) == len(matches)

    def test_an_empty_response_yields_nothing(self) -> None:
        assert parse_web_detection({}) == []

    def test_the_monthly_free_tier_is_taken_into_account(self) -> None:
        engine = VisionSearchEngine()
        assert engine.estimated_cost(500) == 0.0
        assert engine.estimated_cost(1500) == 1.75
        assert engine.estimated_cost(500, already_used=1000) == 1.75

    def test_searching_without_a_key_fails_before_any_request(self) -> None:
        with pytest.raises(MissingApiKey):
            VisionSearchEngine().search([image_bytes(1)])

    def test_large_uploads_are_shrunk(self) -> None:
        big = image_bytes(1, size=(3000, 2000))

        with Image.open(io.BytesIO(shrink(big))) as shrunk:
            assert max(shrunk.size) == 1280
        assert len(shrink(big)) < len(big)


@pytest.fixture
def web_server(tmp_path: Path) -> Iterator[tuple[Path, str]]:
    root = tmp_path / "web"
    root.mkdir()
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(root))
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield root, f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()


class TestHttpFetcher:
    def test_an_image_comes_back_intact(self, web_server: tuple[Path, str]) -> None:
        root, base = web_server
        (root / "photo.png").write_bytes(image_bytes(1))

        with HttpImageFetcher() as fetcher:
            assert fetcher.fetch(f"{base}/photo.png") == image_bytes(1)

    def test_a_missing_url_is_not_an_image(self, web_server: tuple[Path, str]) -> None:
        _, base = web_server
        with HttpImageFetcher() as fetcher:
            assert fetcher.fetch(f"{base}/nope.png") is None

    def test_an_html_page_is_not_an_image(self, web_server: tuple[Path, str]) -> None:
        root, base = web_server
        (root / "page.html").write_text("<html>not an image</html>")

        with HttpImageFetcher() as fetcher:
            assert fetcher.fetch(f"{base}/page.html") is None


class TestLocalFiles:
    def test_profile_pictures_and_messages_are_skipped(self, tmp_path: Path) -> None:
        export = tmp_path / "export" / "media"
        for folder in ("posts", "profile", "messages"):
            (export / folder).mkdir(parents=True)
            (export / folder / "x.png").write_bytes(image_bytes(1))

        found = list(LocalPhotoSource(tmp_path / "export", tmp_path / "work").photos())

        assert [Path(p).parent.name for p in found] == ["posts"]

    def test_a_source_folder_named_like_a_skipped_one_is_still_read(self, tmp_path: Path) -> None:
        # Only folders *inside* the export are skipped; the path you point at is your choice.
        source = tmp_path / "profile"
        source.mkdir()
        (source / "x.png").write_bytes(image_bytes(1))

        assert len(list(LocalPhotoSource(source, tmp_path / "work").photos())) == 1

    def test_the_other_folder_is_your_own_photography(self, tmp_path: Path) -> None:
        # A real export puts the bulk of your pictures under media/other, not media/posts.
        export = tmp_path / "export" / "media"
        for folder in ("posts", "other"):
            (export / folder).mkdir(parents=True)
            (export / folder / "x.png").write_bytes(image_bytes(1))

        found = list(LocalPhotoSource(tmp_path / "export", tmp_path / "work").photos())

        assert sorted(Path(p).parent.name for p in found) == ["other", "posts"]

    def test_a_zip_export_is_unpacked_once(self, tmp_path: Path) -> None:
        archive = tmp_path / "export.zip"
        with zipfile.ZipFile(archive, "w") as zf:
            for name in ("a.png", "b.png"):
                zf.writestr(f"media/posts/{name}", image_bytes(1))
        source = LocalPhotoSource(archive, tmp_path / "work")

        assert len(list(source.photos())) == 2
        assert len(list(source.photos())) == 2, "a second pass must reuse the extraction"

    def test_references_are_absolute_and_loadable(self, tmp_path: Path) -> None:
        (tmp_path / "a.png").write_bytes(image_bytes(1))
        source = LocalPhotoSource(tmp_path, tmp_path)

        reference = next(iter(source.photos()))

        assert Path(reference).is_absolute()
        assert source.load(reference) == image_bytes(1)

    def test_files_that_are_not_images_are_ignored(self, tmp_path: Path) -> None:
        (tmp_path / "notes.txt").write_text("hello")
        (tmp_path / "a.png").write_bytes(image_bytes(1))

        assert len(list(LocalPhotoSource(tmp_path, tmp_path).photos())) == 1


class TestReportWriters:
    def _report(self, repository: SqliteRepository, album: DictPhotoSource) -> Report:
        engine = FakeSearchEngine(
            [
                [
                    Match(
                        MatchKind.FULL,
                        "https://good.example.com/i.jpg",
                        "https://good.example.com/p",
                        "Real",
                    )
                ]
            ]
        )
        fetcher = DictImageFetcher({"https://good.example.com/i.jpg": album.images["/album/a.png"]})
        service = ScanService(repository, repository, engine, album, fetcher)
        service.index(album)
        service.search(service.plan())
        service.verify(workers=2)
        return ReportService(repository, repository).build()

    def test_html_inlines_thumbnails_and_links_the_finding(
        self, repository: SqliteRepository, album: DictPhotoSource, tmp_path: Path
    ) -> None:
        out = tmp_path / "report.html"

        HtmlReportWriter(album).write(self._report(repository, album), out)

        page = out.read_text(encoding="utf-8")
        assert "good.example.com" in page
        assert "data:image/png;base64," in page

    def test_html_survives_a_thumbnail_it_cannot_read(
        self, repository: SqliteRepository, album: DictPhotoSource, tmp_path: Path
    ) -> None:
        out = tmp_path / "report.html"

        HtmlReportWriter(FileImageLoader()).write(self._report(repository, album), out)

        assert 'img src=""' in out.read_text(encoding="utf-8")

    def test_html_escapes_a_hostile_page_title(
        self, album: DictPhotoSource, tmp_path: Path
    ) -> None:
        from imgtrail.domain import Finding, Photo, Report, Summary

        photo = Photo(
            id=1, path="/album/a.png", fingerprint=Fingerprint("ff00ff00ff00ff00"), group_id=1
        )
        nasty = Match(
            MatchKind.FULL,
            "https://x.example.com/i.jpg",
            "https://x.example.com/p",
            "<script>alert(1)</script>",
            Verdict.CONFIRMED,
            1,
        )
        report = Report(Summary(1, 1, 1, {Verdict.CONFIRMED: 1}), (Finding(photo, 1, (nasty,)),))
        out = tmp_path / "report.html"

        HtmlReportWriter(album).write(report, out)

        assert "<script>alert(1)</script>" not in out.read_text(encoding="utf-8")
        assert "&lt;script&gt;" in out.read_text(encoding="utf-8")

    def test_an_empty_report_says_so(
        self, repository: SqliteRepository, album: DictPhotoSource, tmp_path: Path
    ) -> None:
        service = ScanService(repository, repository, FakeSearchEngine(), album, DictImageFetcher())
        service.index(album)
        out = tmp_path / "report.html"

        HtmlReportWriter(album).write(ReportService(repository, repository).build(), out)

        assert "None of your photos turned up" in out.read_text(encoding="utf-8")

    def test_json_is_machine_readable(
        self, repository: SqliteRepository, album: DictPhotoSource, tmp_path: Path
    ) -> None:
        import json

        out = tmp_path / "findings.json"
        JsonReportWriter().write(self._report(repository, album), out)

        payload = json.loads(out.read_text(encoding="utf-8"))
        assert payload["summary"]["unique"] == 3
        assert payload["findings"][0]["matches"][0]["domain"] == "good.example.com"


class TestVisionOverHttp:
    """The request/response path against a real server speaking Vision's JSON."""

    @staticmethod
    def _serve(payloads: list[dict[str, Any]], recorder: list[dict[str, Any]]) -> Iterator[str]:
        class Handler(http.server.BaseHTTPRequestHandler):
            def do_POST(self) -> None:
                body = self.rfile.read(int(self.headers["Content-Length"]))
                recorder.append(json.loads(body))
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps(payloads.pop(0)).encode())

            def log_message(self, *args: object) -> None:
                pass

        httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        yield f"http://127.0.0.1:{httpd.server_address[1]}/annotate"
        httpd.shutdown()

    def test_a_batch_becomes_one_request_per_sixteen_images(self) -> None:
        sent: list[dict[str, Any]] = []
        empty: dict[str, Any] = {"responses": [{"webDetection": {}} for _ in range(16)]}
        payloads = [empty, {"responses": [{"webDetection": {}}]}]
        endpoint = next(self._serve(payloads, sent))

        engine = VisionSearchEngine("key", endpoint=endpoint)
        results = engine.search([image_bytes(i % 5) for i in range(17)])
        engine.close()

        assert len(results) == 17
        assert len(sent) == 2, "17 images at a cap of 16 is two requests"
        assert len(sent[0]["requests"]) == 16

    def test_matches_come_back_in_the_order_asked(self) -> None:
        sent: list[dict[str, Any]] = []
        payload = {
            "responses": [
                {"webDetection": {"fullMatchingImages": [{"url": "https://one.example/a.jpg"}]}},
                {"webDetection": {"fullMatchingImages": [{"url": "https://two.example/b.jpg"}]}},
            ]
        }
        endpoint = next(self._serve([payload], sent))

        engine = VisionSearchEngine("key", endpoint=endpoint)
        results = engine.search([image_bytes(1), image_bytes(2)])
        engine.close()

        assert [m[0].domain for m in results] == ["one.example", "two.example"]

    def test_an_api_error_is_raised_not_swallowed(self) -> None:
        sent: list[dict[str, Any]] = []
        payload = {"responses": [{"error": {"message": "API key not valid"}}]}
        endpoint = next(self._serve([payload], sent))

        engine = VisionSearchEngine("bad", endpoint=endpoint)
        with pytest.raises(RuntimeError, match="API key not valid"):
            engine.search([image_bytes(1)])
        engine.close()
