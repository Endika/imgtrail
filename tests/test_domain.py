"""The rules, tested without a database, a network or a filesystem in sight."""

from __future__ import annotations

import pytest

from imgtrail.domain import (
    Fingerprint,
    Match,
    MatchKind,
    Verdict,
    group_by_similarity,
    is_own_platform,
    verdict_for,
)

from .conftest import image_bytes, repost_bytes


class TestFingerprint:
    def test_a_repost_is_recognised_as_the_same_photo(self) -> None:
        original = Fingerprint.of(image_bytes(1))
        assert original.distance_to(Fingerprint.of(repost_bytes(1))) <= 6

    def test_a_different_photo_is_far_away(self) -> None:
        assert Fingerprint.of(image_bytes(1)).distance_to(Fingerprint.of(image_bytes(99))) > 16

    def test_distance_is_symmetric_and_zero_against_itself(self) -> None:
        one, two = Fingerprint.of(image_bytes(3)), Fingerprint.of(image_bytes(4))
        assert one.distance_to(one) == 0
        assert one.distance_to(two) == two.distance_to(one)


class TestVerdict:
    @pytest.mark.parametrize(
        ("distance", "expected"),
        [
            (0, Verdict.CONFIRMED),
            (8, Verdict.CONFIRMED),
            (9, Verdict.LIKELY),
            (16, Verdict.LIKELY),
            (17, Verdict.REJECTED),
            (64, Verdict.REJECTED),
        ],
    )
    def test_boundaries(self, distance: int, expected: Verdict) -> None:
        assert verdict_for(distance) == expected

    def test_only_confirmed_and_likely_reach_the_report(self) -> None:
        reported = {v for v in Verdict if v.worth_reporting}
        assert reported == {Verdict.CONFIRMED, Verdict.LIKELY}


class TestMatch:
    def test_a_match_must_point_somewhere(self) -> None:
        with pytest.raises(ValueError, match="page or an image"):
            Match(kind=MatchKind.FULL)

    def test_domain_strips_www_and_lowercases(self) -> None:
        assert Match(MatchKind.FULL, page_url="https://www.Example.COM/x").domain == "example.com"

    def test_domain_falls_back_to_the_image_when_there_is_no_page(self) -> None:
        assert Match(MatchKind.FULL, image_url="https://cdn.ex.com/a.jpg").domain == "cdn.ex.com"

    def test_judging_is_pure(self) -> None:
        original = Match(MatchKind.FULL, page_url="https://ex.com")
        judged = original.judged(3)
        assert judged.verdict == Verdict.CONFIRMED and judged.distance == 3
        assert original.verdict == Verdict.PENDING, "the original must not be mutated"

    def test_unreachable_forgets_any_distance(self) -> None:
        judged = Match(MatchKind.FULL, page_url="https://ex.com").judged(3)
        assert judged.unreachable().distance is None


class TestOwnPlatforms:
    @pytest.mark.parametrize(
        "domain", ["instagram.com", "scontent-mad1-1.cdninstagram.com", "www.facebook.com"]
    )
    def test_your_own_platforms_are_not_findings(self, domain: str) -> None:
        assert is_own_platform(domain.removeprefix("www."))

    @pytest.mark.parametrize("domain", ["notinstagram.com", "pinterest.com", None])
    def test_everything_else_is(self, domain: str | None) -> None:
        assert not is_own_platform(domain)


class TestGrouping:
    def test_a_repost_joins_the_original(self) -> None:
        prints = [
            (1, Fingerprint.of(image_bytes(1))),
            (2, Fingerprint.of(repost_bytes(1))),
            (3, Fingerprint.of(image_bytes(99))),
        ]
        assert group_by_similarity(prints) == {1: 1, 2: 1, 3: 3}

    def test_the_first_photo_of_a_group_represents_it(self) -> None:
        prints = [(9, Fingerprint.of(image_bytes(5))), (4, Fingerprint.of(repost_bytes(5)))]
        assert group_by_similarity(prints) == {9: 9, 4: 9}

    def test_a_threshold_of_zero_keeps_everything_apart(self) -> None:
        prints = [(1, Fingerprint.of(image_bytes(1))), (2, Fingerprint.of(repost_bytes(1)))]
        assert group_by_similarity(prints, threshold=0) == {1: 1, 2: 2}

    def test_nothing_in_nothing_out(self) -> None:
        assert group_by_similarity([]) == {}
