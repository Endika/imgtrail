from imgtrail.search import DEFAULT_IGNORED, Hit, estimate_cost, is_ignored, parse_web_detection

RESPONSE = {
    "pagesWithMatchingImages": [
        {
            "url": "https://blog.example.com/post",
            "pageTitle": "A post that used my photo",
            "fullMatchingImages": [{"url": "https://cdn.example.com/mine.jpg"}],
        },
        {
            "url": "https://forum.example.org/thread",
            "partialMatchingImages": [{"url": "https://forum.example.org/t/crop.jpg"}],
        },
        {"url": "https://nolink.example.net/page", "pageTitle": "No image extracted"},
    ],
    "fullMatchingImages": [{"url": "https://cdn.example.com/mine.jpg"}],
    "visuallySimilarImages": [{"url": "https://unrelated.example.com/other.jpg"}],
}


def test_parses_pages_images_and_kinds():
    hits = parse_web_detection(RESPONSE)

    assert Hit("full", "https://blog.example.com/post", "https://cdn.example.com/mine.jpg",
               "A post that used my photo") in hits
    assert any(h.kind == "partial" and h.domain == "forum.example.org" for h in hits)


def test_a_page_without_an_extracted_image_is_still_reported():
    hits = parse_web_detection(RESPONSE)
    page = next(h for h in hits if h.page_url == "https://nolink.example.net/page")
    assert page.image_url is None and page.kind == "partial"


def test_visually_similar_images_are_dropped():
    urls = {h.image_url for h in parse_web_detection(RESPONSE)}
    assert "https://unrelated.example.com/other.jpg" not in urls


def test_the_same_page_image_pair_is_not_reported_twice():
    hits = parse_web_detection(RESPONSE)
    assert len({(h.page_url, h.image_url) for h in hits}) == len(hits)


def test_domain_strips_www_and_falls_back_to_the_image_url():
    assert Hit("full", page_url="https://www.Example.COM/x").domain == "example.com"
    assert Hit("full", image_url="https://cdn.example.com/a.jpg").domain == "cdn.example.com"
    assert Hit("full").domain is None


def test_own_platforms_are_ignored_including_subdomains():
    assert is_ignored("scontent-mad1-1.cdninstagram.com", DEFAULT_IGNORED)
    assert is_ignored("instagram.com", DEFAULT_IGNORED)
    assert not is_ignored("notinstagram.com", DEFAULT_IGNORED)
    assert not is_ignored(None, DEFAULT_IGNORED)


def test_the_monthly_free_tier_is_taken_into_account():
    assert estimate_cost(500) == 0.0
    assert estimate_cost(1500) == 1.75
    assert estimate_cost(500, already_used=1000) == 1.75
