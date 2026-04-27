import httpx

from scraper_hn import HackerNewsScraper


async def test_fetch_posts_dedups_and_prefixes_ids(respx_mock):
    route = respx_mock.get("https://hn.algolia.com/api/v1/search_by_date").mock(
        side_effect=[
            httpx.Response(
                200,
                json={
                    "hits": [
                        {
                            "objectID": "1",
                            "title": "Ask HN: internal tool pain",
                            "story_text": "Our billing sync is fragile",
                            "url": "",
                            "points": 15,
                            "created_at_i": 1713600000,
                            "created_at": "2024-04-20T08:00:00Z",
                        }
                    ]
                },
            ),
            httpx.Response(
                200,
                json={
                    "hits": [
                        {
                            "objectID": "1",  # duplicate across keyword query
                            "title": "Ask HN: internal tool pain",
                            "story_text": "Our billing sync is fragile",
                            "url": "",
                            "points": 15,
                            "created_at_i": 1713600000,
                            "created_at": "2024-04-20T08:00:00Z",
                        },
                        {
                            "objectID": "2",
                            "title": "Frustrating devops handoff",
                            "story_text": "We built our own monitor",
                            "url": "https://example.com/2",
                            "points": 8,
                            "created_at_i": 1713600300,
                            "created_at": "2024-04-20T08:05:00Z",
                        },
                    ]
                },
            ),
        ]
    )
    scraper = HackerNewsScraper(user_agent="test-agent")

    posts = await scraper.fetch_posts(
        keywords=["internal tool", "frustrating"],
        lookback_hours=24,
        max_posts=5,
    )

    assert route.call_count == 2
    assert len(posts) == 2
    ids = {post.post_id for post in posts}
    assert ids == {"hn:1", "hn:2"}
    assert all(post.source == "hn" for post in posts)
    first = next(post for post in posts if post.post_id == "hn:1")
    assert first.source_created_ts == 1713600000
    assert first.source_created_at == "2024-04-20T08:00:00+00:00"


def test_source_created_fields_handles_unhashable_timestamp_with_created_at_fallback():
    created_at, created_ts = HackerNewsScraper._source_created_fields(
        {"created_at_i": ["not", "hashable"], "created_at": "2024-04-20T08:00:00Z"}
    )

    assert created_at == "2024-04-20T08:00:00+00:00"
    assert created_ts == 1713600000


async def test_fetch_posts_handles_http_errors_per_keyword(respx_mock):
    respx_mock.get("https://hn.algolia.com/api/v1/search_by_date").mock(
        side_effect=[
            httpx.Response(503),
            httpx.Response(
                200,
                json={
                    "hits": [
                        {"objectID": "9", "title": "Need better internal tooling", "story_text": "pain", "points": 3}
                    ]
                },
            ),
        ]
    )
    scraper = HackerNewsScraper()
    posts = await scraper.fetch_posts(keywords=["broken", "tooling"], lookback_hours=12, max_posts=10)

    assert len(posts) == 1
    assert posts[0].post_id == "hn:9"


async def test_fetch_posts_returns_empty_on_invalid_input():
    scraper = HackerNewsScraper()
    assert await scraper.fetch_posts(keywords=[], lookback_hours=24, max_posts=10) == []
    assert await scraper.fetch_posts(keywords=["x"], lookback_hours=24, max_posts=0) == []
