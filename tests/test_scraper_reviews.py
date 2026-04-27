from unittest.mock import AsyncMock

from scraper_reviews import ReviewScraper, ReviewTarget


def test_parse_appstore_reviews_from_ld_json():
    html = """
    <html><body>
      <script type="application/ld+json">
      {"@type":"Review","reviewRating":{"ratingValue":"1"},"reviewBody":"Crashes every day","datePublished":"2024-04-20T08:15:00Z"}
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
    assert rows[0]["source_created_ts"] == 1713600900
    assert rows[0]["source_created_at"] == "2024-04-20T08:15:00+00:00"


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


def test_source_created_fields_handles_millisecond_and_invalid_timestamps():
    scraper = ReviewScraper()

    assert scraper._source_created_fields("1713600900000") == ("2024-04-20T08:15:00+00:00", 1713600900)
    assert scraper._source_created_fields("999999999999999999999999") == (None, None)


async def test_fetch_negative_reviews_filters_to_1_and_2_star(monkeypatch):
    html = """
    <article class="review-card" aria-label="1 star">
      <time datetime="2024-04-20T08:15:00Z"></time>
      Completely unusable for invoicing.
    </article>
    <article class="review-card" aria-label="2 stars">
      <time datetime="2024-04-21T09:30:00Z"></time>
      No API retries and poor docs.
    </article>
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
    assert posts[0].source_created_ts == 1713600900
    assert posts[0].source_created_at == "2024-04-20T08:15:00+00:00"


async def test_fetch_negative_reviews_handles_disabled_or_fetch_failure(monkeypatch):
    scraper = ReviewScraper()
    monkeypatch.setattr(scraper, "_fetch_html", AsyncMock(return_value=""))
    disabled_target = ReviewTarget(site="capterra", name="A", url="https://example.com", enabled=False)
    enabled_target = ReviewTarget(site="capterra", name="A", url="https://example.com", enabled=True)

    assert await scraper.fetch_negative_reviews(target=disabled_target, max_reviews=5) == []
    assert await scraper.fetch_negative_reviews(target=enabled_target, max_reviews=5) == []


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


def test_parse_rating_from_text_requires_rating_context():
    scraper = ReviewScraper()
    assert scraper._parse_rating_from_text("2 stars") == 2.0
    assert scraper._parse_rating_from_text("rating 1.5") == 1.5
    assert scraper._parse_rating_from_text("value 2") == 0.0
