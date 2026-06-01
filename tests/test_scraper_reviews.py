from unittest.mock import AsyncMock

import httpx
import pytest

from scraper_reviews import ReviewFetchError, ReviewScraper, ReviewTarget


def test_parse_appstore_reviews_from_ld_json():
    html = """
    <html><body>
      <script type="application/ld+json">
      {"@type":"Review","reviewRating":{"ratingValue":"1"},"reviewBody":"Crashes every day"}
      </script>
      <script type="application/ld+json">
      {"@type":"Review","reviewRating":{"ratingValue":"4"},"reviewBody":"Pretty good"}
      </script>
    </body></html>
    """
    scraper = ReviewScraper()
    rows = scraper._parse_appstore_reviews(html)

    assert len(rows) == 2
    assert rows[0]["rating"] == 1.0
    assert "Crashes" in rows[0]["text"]


def test_parse_appstore_reviews_tolerates_bad_rating_shapes():
    html = """
    <html><body>
      <script type="application/ld+json">
      [
        {"@type":"Review","reviewRating":"bad","reviewBody":"Bad rating shape"},
        {"@type":"Review","reviewRating":{"ratingValue":"not-a-number"},"reviewBody":"Bad rating value"},
        {"@type":"Review","reviewRating":{"ratingValue":"2"},"reviewBody":"Still useful"}
      ]
      </script>
    </body></html>
    """
    scraper = ReviewScraper()
    rows = scraper._parse_appstore_reviews(html)

    assert [row["rating"] for row in rows] == [0.0, 0.0, 2.0]
    assert rows[2]["text"] == "Still useful"


def test_parse_generic_review_cards_extracts_ratings():
    html = """
    <article class="review-card" aria-label="2 stars">
      Very buggy integrations and bad sync behavior.
    </article>
    <article class="review-card">
      <span aria-label="1 star"></span>
      Missing critical export features.
    </article>
    <article class="review-card" aria-label="5 stars">
      Works great.
    </article>
    """
    scraper = ReviewScraper()
    rows = scraper._parse_generic_review_cards(html)

    assert len(rows) >= 2
    assert any(float(row["rating"]) == 2.0 for row in rows)
    assert any("Missing critical export features." in row["text"] for row in rows)


async def test_fetch_negative_reviews_filters_to_1_and_2_star(monkeypatch):
    html = """
    <article class="review-card" aria-label="1 star">Completely unusable for invoicing.</article>
    <article class="review-card" aria-label="2 stars">No API retries and poor docs.</article>
    <article class="review-card" aria-label="3 stars">Usable but rough.</article>
    """
    scraper = ReviewScraper()
    monkeypatch.setattr(scraper, "_fetch_html", AsyncMock(return_value=html))
    target = ReviewTarget(site="g2", name="QuickBooks Sync Tool", url="https://example.com/reviews")

    posts = await scraper.fetch_negative_reviews(target=target, max_reviews=10)

    assert len(posts) == 2
    assert posts[0].post_id.startswith("review:g2:quickbooks-sync-tool:")
    assert all(post.source == "review:g2" for post in posts)
    assert all(post.subreddit == "reviews_g2" for post in posts)


async def test_fetch_negative_reviews_skips_bad_rating_rows(monkeypatch):
    scraper = ReviewScraper()
    monkeypatch.setattr(
        scraper,
        "_parse_generic_review_cards",
        lambda html: [
            {"rating": "not-a-number", "text": "Bad row"},
            {"rating": 2, "text": "Valid complaint"},
        ],
    )
    monkeypatch.setattr(scraper, "_fetch_html", AsyncMock(return_value="<html></html>"))
    target = ReviewTarget(site="g2", name="QuickBooks Sync Tool", url="https://example.com/reviews")

    posts = await scraper.fetch_negative_reviews(target=target, max_reviews=10)

    assert len(posts) == 1
    assert posts[0].body == "Valid complaint"


async def test_fetch_negative_reviews_uses_stable_content_ids(monkeypatch):
    first_html = """
    <article class="review-card" aria-label="1 star">Completely unusable for invoicing.</article>
    <article class="review-card" aria-label="2 stars">No API retries and poor docs.</article>
    """
    reordered_html = """
    <article class="review-card" aria-label="5 stars">Fine for tiny teams.</article>
    <article class="review-card" aria-label="2 stars">No API retries and poor docs.</article>
    <article class="review-card" aria-label="1 star">Completely unusable for invoicing.</article>
    """
    scraper = ReviewScraper()
    target = ReviewTarget(site="g2", name="QuickBooks Sync Tool", url="https://example.com/reviews")

    monkeypatch.setattr(scraper, "_fetch_html", AsyncMock(return_value=first_html))
    first_posts = await scraper.fetch_negative_reviews(target=target, max_reviews=10)
    monkeypatch.setattr(scraper, "_fetch_html", AsyncMock(return_value=reordered_html))
    reordered_posts = await scraper.fetch_negative_reviews(target=target, max_reviews=10)

    assert {post.post_id for post in reordered_posts} == {post.post_id for post in first_posts}


async def test_fetch_negative_reviews_filters_before_applying_limit(monkeypatch):
    html = """
    <article class="review-card" aria-label="5 stars">Good enough.</article>
    <article class="review-card" aria-label="4 stars">Mostly fine.</article>
    <article class="review-card" aria-label="1 star">Lost invoices every week.</article>
    <article class="review-card" aria-label="2 stars">No retry controls.</article>
    """
    scraper = ReviewScraper()
    monkeypatch.setattr(scraper, "_fetch_html", AsyncMock(return_value=html))
    target = ReviewTarget(site="g2", name="QuickBooks Sync Tool", url="https://example.com/reviews")

    posts = await scraper.fetch_negative_reviews(target=target, max_reviews=1)

    assert len(posts) == 1
    assert "Lost invoices" in posts[0].body


async def test_fetch_negative_reviews_handles_disabled_or_fetch_failure(monkeypatch):
    scraper = ReviewScraper()
    monkeypatch.setattr(scraper, "_fetch_html", AsyncMock(return_value=""))
    disabled_target = ReviewTarget(site="capterra", name="A", url="https://example.com", enabled=False)
    enabled_target = ReviewTarget(site="capterra", name="A", url="https://example.com", enabled=True)

    assert await scraper.fetch_negative_reviews(target=disabled_target, max_reviews=5) == []
    assert await scraper.fetch_negative_reviews(target=enabled_target, max_reviews=5) == []


async def test_fetch_negative_reviews_rejects_private_target_url():
    scraper = ReviewScraper()
    target = ReviewTarget(site="g2", name="Internal", url="http://127.0.0.1/reviews")

    with pytest.raises(ReviewFetchError, match="public http or https URL"):
        await scraper.fetch_negative_reviews(target=target, max_reviews=5)


async def test_fetch_html_rejects_target_url_that_resolves_private(monkeypatch):
    scraper = ReviewScraper()
    monkeypatch.setattr("scraper_reviews.is_resolved_public_http_url", AsyncMock(return_value=False))

    with pytest.raises(ReviewFetchError, match="resolve to a public"):
        await scraper._fetch_html("https://reviews.example.test")


async def test_fetch_html_streams_review_response_with_size_limit(monkeypatch, respx_mock):
    scraper = ReviewScraper(max_html_bytes=64)
    monkeypatch.setattr("scraper_reviews.is_resolved_public_http_url", AsyncMock(return_value=True))
    route = respx_mock.get("https://example.com/reviews").mock(
        return_value=httpx.Response(200, content=b"<html>ok</html>")
    )

    html = await scraper._fetch_html("https://example.com/reviews")

    assert route.called
    assert html == "<html>ok</html>"


async def test_fetch_html_rejects_oversized_review_response(monkeypatch, respx_mock):
    scraper = ReviewScraper(max_html_bytes=8)
    monkeypatch.setattr("scraper_reviews.is_resolved_public_http_url", AsyncMock(return_value=True))
    respx_mock.get("https://example.com/reviews").mock(return_value=httpx.Response(200, content=b"123456789"))

    with pytest.raises(ReviewFetchError, match="exceeded 8 bytes"):
        await scraper._fetch_html("https://example.com/reviews")


async def test_fetch_many_targets_combines_results(monkeypatch):
    scraper = ReviewScraper()
    monkeypatch.setattr(
        scraper,
        "fetch_negative_reviews",
        AsyncMock(
            side_effect=[
                [],
                [
                    # minimal compatible objects
                    type("P", (), {"post_id": "review:g2:x:1"})(),
                    type("P", (), {"post_id": "review:g2:x:2"})(),
                ],
            ]
        ),
    )
    targets = [
        ReviewTarget(site="g2", name="A", url="u1"),
        ReviewTarget(site="g2", name="B", url="u2"),
    ]
    rows = await scraper.fetch_many_targets(targets=targets, max_per_target=2)
    assert len(rows) == 2


async def test_fetch_many_targets_tolerates_partial_target_failure(monkeypatch):
    scraper = ReviewScraper()
    monkeypatch.setattr(
        scraper,
        "fetch_negative_reviews",
        AsyncMock(
            side_effect=[
                ReviewFetchError("temporary outage"),
                [
                    type("P", (), {"post_id": "review:g2:x:2"})(),
                ],
            ]
        ),
    )
    targets = [
        ReviewTarget(site="g2", name="A", url="u1"),
        ReviewTarget(site="g2", name="B", url="u2"),
    ]

    rows = await scraper.fetch_many_targets(targets=targets, max_per_target=2)

    assert len(rows) == 1


async def test_fetch_many_targets_raises_when_all_enabled_targets_fail(monkeypatch):
    scraper = ReviewScraper()
    monkeypatch.setattr(
        scraper,
        "fetch_negative_reviews",
        AsyncMock(side_effect=[ReviewFetchError("down"), ReviewFetchError("still down")]),
    )
    targets = [
        ReviewTarget(site="g2", name="A", url="u1"),
        ReviewTarget(site="g2", name="B", url="u2"),
    ]

    with pytest.raises(RuntimeError, match="Review fetch failed for all 2 enabled targets"):
        await scraper.fetch_many_targets(targets=targets, max_per_target=2)


def test_parse_rating_from_text_requires_rating_context():
    scraper = ReviewScraper()
    assert scraper._parse_rating_from_text("2 stars") == 2.0
    assert scraper._parse_rating_from_text("rating 1.5") == 1.5
    assert scraper._parse_rating_from_text("value 2") == 0.0
