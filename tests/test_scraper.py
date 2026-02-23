# tests/test_scraper.py
import pytest
import pytest_asyncio
import httpx
import respx
from scraper import RedditScraper, Post


async def test_post_dataclass_fields():
    p = Post(
        post_id="t3_abc",
        subreddit="python",
        title="Why can't I do X",
        body="I've been trying for hours",
        url="https://reddit.com/r/python/t3_abc",
        score=42,
    )
    assert p.post_id == "t3_abc"
    assert p.title == "Why can't I do X"
    assert p.score == 42


async def test_scraper_no_credentials_sets_use_praw_false():
    scraper = RedditScraper(client_id="", client_secret="", user_agent="test")
    assert scraper._use_praw is False


async def test_scraper_with_credentials_sets_use_praw_true():
    scraper = RedditScraper(client_id="abc", client_secret="xyz", user_agent="test")
    assert scraper._use_praw is True


async def test_fetch_public_json_returns_posts(respx_mock):
    respx_mock.get("https://www.reddit.com/r/python/top.json").mock(
        return_value=httpx.Response(200, json={
            "data": {
                "children": [
                    {"data": {
                        "id": "abc1",
                        "title": "Test post",
                        "selftext": "body text",
                        "url": "https://reddit.com/abc1",
                        "score": 10,
                        "subreddit": "python",
                    }},
                    {"data": {
                        "id": "abc2",
                        "title": "Another post",
                        "selftext": "",
                        "url": "https://reddit.com/abc2",
                        "score": 5,
                        "subreddit": "python",
                    }},
                ]
            }
        })
    )
    scraper = RedditScraper(client_id="", client_secret="", user_agent="test/1.0")
    posts = await scraper._fetch_public_json("python", limit=10)
    assert len(posts) == 2
    assert posts[0].post_id == "abc1"
    assert posts[0].title == "Test post"
    assert posts[0].body == "body text"
    assert posts[1].post_id == "abc2"


async def test_fetch_public_json_handles_http_error(respx_mock):
    respx_mock.get("https://www.reddit.com/r/doesnotexist/top.json").mock(
        return_value=httpx.Response(404)
    )
    scraper = RedditScraper(client_id="", client_secret="", user_agent="test/1.0")
    import pytest
    with pytest.raises(Exception):
        await scraper._fetch_public_json("doesnotexist", limit=10)


async def test_fetch_posts_uses_public_json_when_no_credentials(respx_mock):
    respx_mock.get("https://www.reddit.com/r/python/top.json").mock(
        return_value=httpx.Response(200, json={"data": {"children": []}})
    )
    scraper = RedditScraper(client_id="", client_secret="", user_agent="test/1.0")
    posts = await scraper.fetch_posts("python", limit=5)
    assert isinstance(posts, list)
