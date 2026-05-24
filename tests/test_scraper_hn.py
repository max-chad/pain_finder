import httpx
import pytest

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
                        },
                        {
                            "objectID": "2",
                            "title": "Frustrating devops handoff",
                            "story_text": "We built our own monitor",
                            "url": "https://example.com/2",
                            "points": 8,
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


async def test_fetch_posts_raises_when_all_keyword_requests_fail(respx_mock):
    route = respx_mock.get("https://hn.algolia.com/api/v1/search_by_date").mock(
        side_effect=[
            httpx.Response(503),
            httpx.Response(429),
        ]
    )
    scraper = HackerNewsScraper()

    with pytest.raises(RuntimeError, match="HN fetch failed for all 2 keyword queries"):
        await scraper.fetch_posts(keywords=["broken", "rate limit"], lookback_hours=12, max_posts=10)

    assert route.call_count == 2


async def test_fetch_posts_returns_empty_on_invalid_input():
    scraper = HackerNewsScraper()
    assert await scraper.fetch_posts(keywords=[], lookback_hours=24, max_posts=10) == []
    assert await scraper.fetch_posts(keywords=["x"], lookback_hours=24, max_posts=0) == []
