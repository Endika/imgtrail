"""The use cases, driven through their ports with in-memory doubles."""

from __future__ import annotations

from imgtrail.adapters.sqlite_repository import SqliteRepository
from imgtrail.domain import Match, MatchKind, Verdict
from imgtrail.services import ReportService, ScanPlan, ScanService

from .conftest import (
    DictImageFetcher,
    DictPhotoSource,
    FakeSearchEngine,
    flat_bytes,
    image_bytes,
)


def build(
    repository: SqliteRepository,
    album: DictPhotoSource,
    engine: FakeSearchEngine | None = None,
    fetcher: DictImageFetcher | None = None,
) -> tuple[ScanService, FakeSearchEngine, DictImageFetcher]:
    engine = engine or FakeSearchEngine()
    fetcher = fetcher or DictImageFetcher()
    service = ScanService(repository, repository, engine, album, fetcher, repository)
    return service, engine, fetcher


def blog(
    url: str = "https://blog.example.com/post",
    image: str = "https://blog.example.com/i.jpg",
) -> Match:
    return Match(MatchKind.FULL, page_url=url, image_url=image, title="A post")


class TestIndexing:
    def test_reposts_collapse_so_they_are_never_searched_twice(
        self, repository: SqliteRepository, album: DictPhotoSource
    ) -> None:
        service, _, _ = build(repository, album)

        result = service.index(album)

        assert (result.total, result.unique, result.duplicates_saved) == (4, 3, 1)

    def test_indexing_twice_adds_nothing(
        self, repository: SqliteRepository, album: DictPhotoSource
    ) -> None:
        service, _, _ = build(repository, album)
        service.index(album)

        again = service.index(album)

        assert again.added == 0 and again.total == 4

    def test_an_unreadable_file_is_counted_and_skipped(self, repository: SqliteRepository) -> None:
        broken = DictPhotoSource(
            {"/album/ok.png": image_bytes(1), "/album/bad.png": b"not an image"}
        )
        service, _, _ = build(repository, broken)

        result = service.index(broken)

        assert result.unreadable == 1 and result.total == 1

    def test_the_threshold_is_honoured(
        self, repository: SqliteRepository, album: DictPhotoSource
    ) -> None:
        service, _, _ = build(repository, album)

        assert service.index(album, threshold=0).unique == 4


class TestPlanning:
    def test_a_plan_covers_every_unique_photo(
        self, repository: SqliteRepository, album: DictPhotoSource
    ) -> None:
        service, _, _ = build(repository, album)
        service.index(album)

        assert len(service.plan()) == 3

    def test_a_limit_caps_the_plan(
        self, repository: SqliteRepository, album: DictPhotoSource
    ) -> None:
        service, _, _ = build(repository, album)
        service.index(album)

        assert len(service.plan(limit=2)) == 2

    def test_a_flat_frame_is_never_worth_searching(self, repository: SqliteRepository) -> None:
        """It matches every other flat frame online, so the money buys 118 false positives."""
        album = DictPhotoSource({"/album/black.png": flat_bytes(), "/album/b.png": image_bytes(9)})
        service, _, _ = build(repository, album)
        service.index(album)

        plan = service.plan()

        assert [p.path for p in plan.pending] == ["/album/b.png"]
        assert plan.flat == 1

    def test_a_plan_stays_inside_the_source_it_was_pointed_at(
        self, repository: SqliteRepository
    ) -> None:
        """Pointing at seven photos must not plan a search over the whole database."""
        both = DictPhotoSource({"/album/a.png": image_bytes(1), "/other/x.png": image_bytes(42)})
        service, _, _ = build(repository, both)
        service.index(both)

        assert [p.path for p in service.plan(under="/other/").pending] == ["/other/x.png"]
        assert len(service.plan()) == 2, "unscoped, it still covers everything"

    def test_again_plans_the_photos_already_paid_for(
        self, repository: SqliteRepository, album: DictPhotoSource
    ) -> None:
        service, _, _ = build(repository, album)
        service.index(album)
        service.search(service.plan())
        assert len(service.plan()) == 0, "without it, a second scan finds nothing to do"

        again = service.plan(again=True)

        assert len(again) == 3
        assert again.already_searched == 0, "it repeats them all, so none is left out"

    def test_planning_calls_no_engine(
        self, repository: SqliteRepository, album: DictPhotoSource
    ) -> None:
        service, engine, _ = build(repository, album)
        service.index(album)

        service.plan()

        assert engine.calls == 0


class TestSearching:
    def test_only_matches_outside_your_own_platforms_are_kept(
        self, repository: SqliteRepository, album: DictPhotoSource
    ) -> None:
        engine = FakeSearchEngine(
            [
                [
                    blog(),
                    Match(
                        MatchKind.FULL,
                        "https://i.instagram.com/x.jpg",
                        page_url="https://www.instagram.com/p/abc",
                    ),
                    Match(MatchKind.PARTIAL, "https://scontent.cdninstagram.com/i.jpg"),
                ]
            ]
        )
        service, _, _ = build(repository, album, engine)
        service.index(album)

        stored = service.search(service.plan())

        assert stored == 1
        assert [m.domain for _, m in repository.findings([Verdict.PENDING])] == ["blog.example.com"]

    def test_extra_ignored_domains_are_honoured(
        self, repository: SqliteRepository, album: DictPhotoSource
    ) -> None:
        engine = FakeSearchEngine(
            [
                [
                    blog(),
                    Match(
                        MatchKind.FULL,
                        "https://i.pinimg.com/1.jpg",
                        page_url="https://pinterest.com/pin/1",
                    ),
                ]
            ]
        )
        service, _, _ = build(repository, album, engine)
        service.index(album)

        service.search(service.plan(), own_platforms={"pinterest.com"})

        found = {m.domain for _, m in repository.findings([Verdict.PENDING])}
        assert found == {"blog.example.com"}

    def test_every_unique_photo_is_sent_exactly_once(
        self, repository: SqliteRepository, album: DictPhotoSource
    ) -> None:
        service, engine, _ = build(repository, album)
        service.index(album)

        service.search(service.plan())

        assert len(engine.images_seen) == 3

    def test_the_engine_batch_size_is_respected(
        self, repository: SqliteRepository, album: DictPhotoSource
    ) -> None:
        service, engine, _ = build(repository, album)
        service.index(album)

        service.search(service.plan())

        assert engine.calls == 2, "three photos at batch_size 2 means two calls"

    def test_rerunning_costs_nothing(
        self, repository: SqliteRepository, album: DictPhotoSource
    ) -> None:
        service, engine, _ = build(repository, album)
        service.index(album)
        service.search(service.plan())
        before = engine.calls

        service.search(service.plan())

        assert engine.calls == before and len(service.plan()) == 0

    def test_progress_is_reported_per_batch(
        self, repository: SqliteRepository, album: DictPhotoSource
    ) -> None:
        service, _, _ = build(repository, album)
        service.index(album)
        seen: list[int] = []

        service.search(service.plan(), on_batch=seen.append)

        assert sum(seen) == 3


class TestReparsing:
    def test_correcting_a_filter_costs_no_search(
        self, repository: SqliteRepository, album: DictPhotoSource
    ) -> None:
        """The point of keeping the payload: the money was spent, the judgement was wrong."""
        engine = FakeSearchEngine([[blog()]])
        service, _, _ = build(repository, album, engine)
        service.index(album)
        service.search(service.plan(), own_platforms={"blog.example.com"})
        assert repository.tally() == {}, "the filter of the day threw it away"
        paid_for = engine.calls

        recovered = service.reparse(own_platforms=set())

        assert recovered == 1
        assert engine.calls == paid_for, "a reparse must never reach the engine"
        assert {m.domain for m, _ in repository.awaiting_verdict()} == {"blog.example.com"}

    def test_an_existing_verdict_is_not_thrown_away(
        self, repository: SqliteRepository, album: DictPhotoSource
    ) -> None:
        engine = FakeSearchEngine([[blog()]])
        fetcher = DictImageFetcher({"https://blog.example.com/i.jpg": album.images["/album/a.png"]})
        service, _, _ = build(repository, album, engine, fetcher)
        service.index(album)
        service.search(service.plan())
        service.verify(workers=1)

        assert service.reparse() == 0
        assert repository.tally() == {Verdict.CONFIRMED: 1}


class TestVerifying:
    def _scanned(
        self,
        repository: SqliteRepository,
        album: DictPhotoSource,
        matches: list[Match],
        downloads: dict[str, bytes | None],
    ) -> tuple[ScanService, DictImageFetcher]:
        service, _, fetcher = build(
            repository, album, FakeSearchEngine([matches]), DictImageFetcher(downloads)
        )
        service.index(album)
        service.search(service.plan())
        return service, fetcher

    def test_the_same_image_is_confirmed(
        self, repository: SqliteRepository, album: DictPhotoSource
    ) -> None:
        original = album.images["/album/a.png"]
        service, _ = self._scanned(
            repository, album, [blog()], {"https://blog.example.com/i.jpg": original}
        )

        tally = service.verify(workers=2)

        assert tally == {Verdict.CONFIRMED: 1}

    def test_an_unrelated_image_is_rejected(
        self, repository: SqliteRepository, album: DictPhotoSource
    ) -> None:
        service, _ = self._scanned(
            repository, album, [blog()], {"https://blog.example.com/i.jpg": image_bytes(1234)}
        )

        assert service.verify(workers=2) == {Verdict.REJECTED: 1}

    def test_an_undownloadable_candidate_is_unreachable(
        self, repository: SqliteRepository, album: DictPhotoSource
    ) -> None:
        service, _ = self._scanned(repository, album, [blog()], {})

        assert service.verify(workers=2) == {Verdict.UNREACHABLE: 1}

    def test_an_unfetchable_url_is_unreachable_not_rejected(
        self, repository: SqliteRepository, album: DictPhotoSource
    ) -> None:
        service, fetcher = self._scanned(repository, album, [blog()], {})

        assert service.verify(workers=2) == {Verdict.UNREACHABLE: 1}
        assert fetcher.requested == ["https://blog.example.com/i.jpg"]

    def test_garbage_bytes_do_not_crash_the_run(
        self, repository: SqliteRepository, album: DictPhotoSource
    ) -> None:
        service, _ = self._scanned(
            repository, album, [blog()], {"https://blog.example.com/i.jpg": b"<html>"}
        )

        assert service.verify(workers=2) == {Verdict.UNREACHABLE: 1}

    def test_verifying_twice_downloads_nothing_the_second_time(
        self, repository: SqliteRepository, album: DictPhotoSource
    ) -> None:
        original = album.images["/album/a.png"]
        service, fetcher = self._scanned(
            repository, album, [blog()], {"https://blog.example.com/i.jpg": original}
        )
        service.verify(workers=2)
        before = len(fetcher.requested)

        assert service.verify(workers=2) == {}
        assert len(fetcher.requested) == before


class TestReporting:
    def test_rejected_matches_never_reach_the_report(
        self, repository: SqliteRepository, album: DictPhotoSource
    ) -> None:
        engine = FakeSearchEngine(
            [
                [
                    blog("https://good.example.com/p", "https://good.example.com/i.jpg"),
                    blog("https://bad.example.com/p", "https://bad.example.com/i.jpg"),
                ]
            ]
        )
        fetcher = DictImageFetcher(
            {
                "https://good.example.com/i.jpg": album.images["/album/a.png"],
                "https://bad.example.com/i.jpg": image_bytes(1234),
            }
        )
        service, _, _ = build(repository, album, engine, fetcher)
        service.index(album)
        service.search(service.plan())
        service.verify(workers=2)

        report = ReportService(repository, repository).build()

        domains = {m.domain for f in report.findings for m in f.matches}
        assert domains == {"good.example.com"}

    def test_a_flat_frame_reports_nothing_however_it_was_matched(
        self, repository: SqliteRepository
    ) -> None:
        """Rows searched before the fix are still in the database, and stay out anyway."""
        album = DictPhotoSource({"/album/black.png": flat_bytes()})
        engine = FakeSearchEngine([[blog()]])
        fetcher = DictImageFetcher({"https://blog.example.com/i.jpg": flat_bytes()})
        service, _, _ = build(repository, album, engine, fetcher)
        service.index(album)
        service.search(
            ScanPlan(
                pending=tuple(repository.representatives_awaiting_search()),
                already_searched=0,
                engine_name="fake",
                cost=0.0,
            )
        )
        service.verify(workers=1)

        assert ReportService(repository, repository).build().findings == ()

    def test_a_candidate_that_would_not_download_is_a_lead_not_a_silence(
        self, repository: SqliteRepository, album: DictPhotoSource
    ) -> None:
        """353 of these vanished from a real report without a word."""
        service, _, _ = build(repository, album, FakeSearchEngine([[blog()]]), DictImageFetcher())
        service.index(album)
        service.search(service.plan())
        service.verify(workers=1)

        report = ReportService(repository, repository).build()

        assert report.findings == ()
        assert [lead.page_url for e in report.unverified for lead in e.leads] == [
            "https://blog.example.com/post"
        ]

    def test_a_finding_knows_how_many_copies_you_posted(
        self, repository: SqliteRepository, album: DictPhotoSource
    ) -> None:
        engine = FakeSearchEngine([[blog()]])
        fetcher = DictImageFetcher({"https://blog.example.com/i.jpg": album.images["/album/a.png"]})
        service, _, _ = build(repository, album, engine, fetcher)
        service.index(album)
        service.search(service.plan())
        service.verify(workers=2)

        report = ReportService(repository, repository).build()

        assert report.findings[0].copies == 2, "a.png and its repost"

    def test_an_empty_report_still_summarises(
        self, repository: SqliteRepository, album: DictPhotoSource
    ) -> None:
        service, _, _ = build(repository, album)
        service.index(album)

        report = ReportService(repository, repository).build()

        assert report.findings == ()
        assert (report.summary.photos, report.summary.unique) == (4, 3)
