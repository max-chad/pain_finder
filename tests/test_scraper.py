import asyncio

import pytest
import httpx

from scraper import Post, RedditScraper


async def test_post_dataclass_fields():
    post = Post(
        post_id="t3_abc",
        subreddit="python",
        title="Why can't I do X",
        body="I've been trying for hours",
        url="https://reddit.com/r/python/t3_abc",
        score=42,
        permalink="/r/python/comments/t3_abc/example/",
        top_comments=["same issue"],
        source_created_at="2026-04-20T10:00:00Z",
        source_created_ts=1776688800,
        author_name="alice",
    )
    assert post.post_id == "t3_abc"
    assert post.top_comments == ["same issue"]
    assert post.source_created_ts == 1776688800
    assert post.author_name == "alice"


async def test_scraper_no_credentials_sets_use_praw_false():
    scraper = RedditScraper(client_id="", client_secret="", user_agent="test")
    assert scraper._use_praw is False


async def test_scraper_with_credentials_sets_use_praw_true():
    scraper = RedditScraper(client_id="abc", client_secret="xyz", user_agent="test")
    assert scraper._use_praw is True


def test_validate_subreddit_rejects_malformed_values():
    scraper = RedditScraper(client_id="", client_secret="", user_agent="test")

    assert scraper._validate_subreddit("Python") == "python"
    for value in ("", "p", "../api", "python.json", "py-thon", "a" * 22):
        with pytest.raises(ValueError, match="Invalid subreddit"):
            scraper._validate_subreddit(value)


async def test_fetch_posts_rejects_invalid_subreddit_before_network(monkeypatch):
    from unittest.mock import AsyncMock

    scraper = RedditScraper(client_id="", client_secret="", user_agent="test")
    fetch_mock = AsyncMock()
    monkeypatch.setattr(scraper, "_fetch_public_json", fetch_mock)

    with pytest.raises(ValueError, match="Invalid subreddit"):
        await scraper.fetch_posts("../api", limit=5)

    fetch_mock.assert_not_awaited()


async def test_scraper_comment_fetch_concurrency_is_clamped_to_at_least_one():
    scraper = RedditScraper(
        client_id="",
        client_secret="",
        user_agent="test",
        comment_fetch_concurrency=0,
    )
    assert scraper.comment_fetch_concurrency == 1


async def test_fetch_public_json_returns_posts_with_top_comments(respx_mock):
    respx_mock.get("https://www.reddit.com/r/python/top.json").mock(
        return_value=httpx.Response(
            200,
            json={
                "data": {
                    "children": [
                        {
                            "data": {
                                "id": "abc1",
                                "title": "Test post",
                                "selftext": "body text",
                                "url": "https://reddit.com/abc1",
                                "score": 10,
                                "created_utc": 1713600000,
                                "author": "alice",
                                "subreddit": "python",
                                "permalink": "/r/python/comments/abc1/test_post/",
                            }
                        }
                    ]
                }
            },
        )
    )
    respx_mock.get("https://www.reddit.com/comments/abc1.json").mock(
        return_value=httpx.Response(
            200,
            json=[
                {},
                {
                    "data": {
                        "children": [
                            {"kind": "t1", "data": {"body": "first top comment"}},
                            {"kind": "t1", "data": {"body": "second top comment"}},
                        ]
                    }
                },
            ],
        )
    )

    scraper = RedditScraper(client_id="", client_secret="", user_agent="test/1.0", top_comments_limit=2)
    posts = await scraper._fetch_public_json("python", limit=10)

    assert len(posts) == 1
    assert posts[0].post_id == "reddit:abc1"
    assert posts[0].top_comments == ["first top comment", "second top comment"]
    assert "Top comments:" in posts[0].body
    assert posts[0].source_created_ts == 1713600000
    assert posts[0].source_created_at == "2024-04-20T08:00:00+00:00"
    assert posts[0].author_name == "alice"


def test_parse_rss_entries_preserves_source_timestamp_and_author():
    xml_text = """
    <feed xmlns="http://www.w3.org/2005/Atom">
      <entry>
        <id>tag:reddit.com,2005:comments/abc123</id>
        <title>Manual payroll process still breaks</title>
        <published>2026-04-19T08:15:00+00:00</published>
        <updated>2026-04-21T08:15:00+00:00</updated>
        <author><name>ops_owner</name></author>
        <summary>We still export CSV files every Friday.</summary>
        <link href="https://old.reddit.com/r/smallbusiness/comments/abc123/payroll/" />
      </entry>
    </feed>
    """

    posts = RedditScraper._parse_rss_entries("smallbusiness", xml_text)

    assert len(posts) == 1
    assert posts[0].post_id == "reddit:abc123"
    assert posts[0].source_created_at == "2026-04-19T08:15:00+00:00"
    assert posts[0].source_created_ts == 1776586500
    assert posts[0].author_name == "ops_owner"


def test_merge_post_keeps_earliest_source_timestamp():
    posts_by_id = {
        "reddit:abc123": Post(
            post_id="reddit:abc123",
            subreddit="smallbusiness",
            title="Older",
            body="",
            url="https://reddit.com/r/smallbusiness/comments/abc123/older/",
            score=5,
            source_created_at="2026-04-19T08:15:00+00:00",
            source_created_ts=1776586500,
        )
    }
    newer_variant = Post(
        post_id="reddit:abc123",
        subreddit="smallbusiness",
        title="Newer",
        body="",
        url="https://reddit.com/r/smallbusiness/comments/abc123/newer/",
        score=10,
        source_created_at="2026-04-21T08:15:00+00:00",
        source_created_ts=1776759300,
    )

    RedditScraper._merge_post(posts_by_id, newer_variant)

    assert posts_by_id["reddit:abc123"].score == 10
    assert posts_by_id["reddit:abc123"].source_created_at == "2026-04-19T08:15:00+00:00"
    assert posts_by_id["reddit:abc123"].source_created_ts == 1776586500


def test_build_post_tolerates_malformed_score():
    post = RedditScraper._build_post(
        "python",
        {
            "id": "abc1",
            "title": "Manual workflow pain",
            "selftext": "body",
            "url": "https://reddit.com/abc1",
            "score": "not-an-int",
            "permalink": "/r/python/comments/abc1/manual/",
        },
    )

    assert post is not None
    assert post.post_id == "reddit:abc1"
    assert post.score == 0


async def test_fetch_public_json_handles_http_error(respx_mock):
    respx_mock.get("https://www.reddit.com/r/doesnotexist/top.json").mock(
        return_value=httpx.Response(404)
    )
    scraper = RedditScraper(client_id="", client_secret="", user_agent="test/1.0")
    with pytest.raises(httpx.HTTPStatusError):
        await scraper._fetch_public_json("doesnotexist", limit=10)


async def test_fetch_posts_uses_public_json_when_no_credentials(respx_mock):
    respx_mock.get("https://www.reddit.com/r/python/top.json").mock(
        return_value=httpx.Response(200, json={"data": {"children": []}})
    )
    scraper = RedditScraper(client_id="", client_secret="", user_agent="test/1.0")
    posts = await scraper.fetch_posts("python", limit=5)
    assert isinstance(posts, list)


async def test_fetch_posts_uses_praw_when_credentials_set():
    from unittest.mock import AsyncMock, patch

    scraper = RedditScraper(client_id="abc", client_secret="xyz", user_agent="test")
    expected = [
        Post(
            post_id="p1",
            subreddit="python",
            title="T",
            body="",
            url="",
            score=1,
        )
    ]

    with patch.object(scraper, "_fetch_praw", new=AsyncMock(return_value=expected)):
        posts = await scraper.fetch_posts("python", limit=10)

    assert posts == expected


async def test_fetch_posts_falls_back_to_public_json_on_praw_failure(respx_mock):
    from unittest.mock import AsyncMock, patch

    respx_mock.get("https://www.reddit.com/r/python/top.json").mock(
        return_value=httpx.Response(200, json={"data": {"children": []}})
    )
    scraper = RedditScraper(client_id="abc", client_secret="xyz", user_agent="test")

    with patch.object(scraper, "_fetch_praw", new=AsyncMock(side_effect=Exception("PRAW down"))):
        posts = await scraper.fetch_posts("python", limit=5)

    assert isinstance(posts, list)


async def test_fetch_posts_falls_back_to_oauth_before_public_json():
    from unittest.mock import AsyncMock, patch

    scraper = RedditScraper(client_id="abc", client_secret="xyz", user_agent="test")
    oauth_posts = [
        Post(
            post_id="reddit:o1",
            subreddit="python",
            title="OAuth post",
            body="",
            url="",
            score=1,
        )
    ]

    with (
        patch.object(scraper, "_fetch_praw", new=AsyncMock(side_effect=Exception("PRAW down"))),
        patch.object(scraper, "_fetch_oauth_json", new=AsyncMock(return_value=oauth_posts)) as oauth_mock,
        patch.object(scraper, "_fetch_public_json", new=AsyncMock(return_value=[])) as public_mock,
    ):
        posts = await scraper.fetch_posts("python", limit=5)

    assert posts == oauth_posts
    oauth_mock.assert_awaited_once()
    public_mock.assert_not_called()


async def test_fetch_posts_falls_back_to_public_json_when_oauth_also_fails():
    from unittest.mock import AsyncMock, patch

    scraper = RedditScraper(client_id="abc", client_secret="xyz", user_agent="test")
    public_posts = [
        Post(
            post_id="reddit:p1",
            subreddit="python",
            title="Public fallback",
            body="",
            url="",
            score=1,
        )
    ]

    with (
        patch.object(scraper, "_fetch_praw", new=AsyncMock(side_effect=Exception("PRAW down"))),
        patch.object(scraper, "_fetch_oauth_json", new=AsyncMock(side_effect=Exception("OAuth down"))) as oauth_mock,
        patch.object(scraper, "_fetch_public_json", new=AsyncMock(return_value=public_posts)) as public_mock,
    ):
        posts = await scraper.fetch_posts("python", limit=5)

    assert posts == public_posts
    oauth_mock.assert_awaited_once()
    public_mock.assert_awaited_once()


async def test_fetch_full_thread_falls_back_from_praw_to_oauth_to_public_json():
    from unittest.mock import AsyncMock, patch

    scraper = RedditScraper(client_id="abc", client_secret="xyz", user_agent="test")

    with (
        patch.object(scraper, "_fetch_full_thread_praw", new=AsyncMock(side_effect=Exception("PRAW down"))),
        patch.object(scraper, "_fetch_full_thread_oauth", new=AsyncMock(side_effect=Exception("OAuth down"))) as oauth_mock,
        patch.object(scraper, "_fetch_full_thread_json", new=AsyncMock(return_value=["c1", "c2"])) as json_mock,
    ):
        comments = await scraper.fetch_full_thread("python", "reddit:abc1", max_comments=5)

    assert comments == ["c1", "c2"]
    oauth_mock.assert_awaited_once()
    json_mock.assert_awaited_once_with("reddit:abc1", 5)


async def test_request_oauth_json_refreshes_token_on_401():
    from unittest.mock import AsyncMock, patch

    request = httpx.Request("GET", "https://oauth.reddit.com/r/python/top.json")
    unauthorized = httpx.Response(401, request=request)

    scraper = RedditScraper(client_id="abc", client_secret="xyz", user_agent="test")
    client = AsyncMock()

    with (
        patch.object(scraper, "_get_oauth_token", new=AsyncMock(side_effect=["token1", "token2"])) as token_mock,
        patch.object(
            scraper,
            "_request_json_with_retries",
            new=AsyncMock(side_effect=[httpx.HTTPStatusError("unauthorized", request=request, response=unauthorized), {"data": "ok"}]),
        ) as request_mock,
    ):
        payload = await scraper._request_oauth_json(client=client, path="/r/python/top.json", params={"limit": 5})

    assert payload == {"data": "ok"}
    assert token_mock.await_count == 2
    assert request_mock.await_count == 2


async def test_fetch_public_json_mixes_multiple_feeds_and_deduplicates(respx_mock):
    respx_mock.get("https://www.reddit.com/r/python/top.json").mock(
        return_value=httpx.Response(
            200,
            json={
                "data": {
                    "children": [
                        {
                            "data": {
                                "id": "same",
                                "title": "Top duplicate",
                                "selftext": "body",
                                "url": "https://reddit.com/same",
                                "score": 10,
                                "permalink": "/r/python/comments/same/top/",
                            }
                        }
                    ]
                }
            },
        )
    )
    respx_mock.get("https://www.reddit.com/r/python/new.json").mock(
        return_value=httpx.Response(
            200,
            json={
                "data": {
                    "children": [
                        {
                            "data": {
                                "id": "same",
                                "title": "New duplicate",
                                "selftext": "body",
                                "url": "https://reddit.com/same",
                                "score": 11,
                                "permalink": "/r/python/comments/same/new/",
                            }
                        },
                        {
                            "data": {
                                "id": "fresh",
                                "title": "Fresh post",
                                "selftext": "body2",
                                "url": "https://reddit.com/fresh",
                                "score": 8,
                                "permalink": "/r/python/comments/fresh/new/",
                            }
                        },
                    ]
                }
            },
        )
    )
    respx_mock.get("https://www.reddit.com/comments/same.json").mock(
        return_value=httpx.Response(200, json=[{}, {"data": {"children": []}}])
    )
    respx_mock.get("https://www.reddit.com/comments/fresh.json").mock(
        return_value=httpx.Response(200, json=[{}, {"data": {"children": []}}])
    )

    scraper = RedditScraper(
        client_id="",
        client_secret="",
        user_agent="test/1.0",
        top_comments_limit=1,
        feed_mix=["top", "new"],
    )
    posts = await scraper._fetch_public_json("python", limit=5)

    assert {post.post_id for post in posts} == {"reddit:same", "reddit:fresh"}


async def test_fetch_public_json_keeps_successful_feed_when_peer_feed_fails():
    from unittest.mock import patch

    scraper = RedditScraper(
        client_id="",
        client_secret="",
        user_agent="test/1.0",
        top_comments_limit=0,
        feed_mix=["top", "new"],
    )

    async def payload_or_error(*, client, url, params, headers):
        if url.endswith("/top.json"):
            raise RuntimeError("top feed unavailable")
        return {
            "data": {
                "children": [
                    {
                        "data": {
                            "id": "newonly",
                            "title": "New feed pain",
                            "selftext": "manual sync still breaks",
                            "url": "https://reddit.com/newonly",
                            "score": 8,
                            "permalink": "/r/python/comments/newonly/new-feed-pain/",
                        }
                    }
                ]
            }
        }

    with patch.object(scraper, "_request_json_with_retries", side_effect=payload_or_error):
        posts = await scraper._fetch_public_json("python", limit=10)

    assert [post.post_id for post in posts] == ["reddit:newonly"]


async def test_fetch_public_json_merges_search_queries_and_preserves_discovery_query(respx_mock):
    respx_mock.get("https://www.reddit.com/r/python/top.json").mock(
        return_value=httpx.Response(
            200,
            json={
                "data": {
                    "children": [
                        {
                            "data": {
                                "id": "same",
                                "title": "Top duplicate",
                                "selftext": "body",
                                "url": "https://reddit.com/same",
                                "score": 10,
                                "permalink": "/r/python/comments/same/top/",
                            }
                        }
                    ]
                }
            },
        )
    )
    search_route = respx_mock.get("https://www.reddit.com/r/python/search.json").mock(
        return_value=httpx.Response(
            200,
            json={
                "data": {
                    "children": [
                        {
                            "data": {
                                "id": "same",
                                "title": "Top duplicate",
                                "selftext": "body",
                                "url": "https://reddit.com/same",
                                "score": 10,
                                "permalink": "/r/python/comments/same/top/",
                            }
                        },
                        {
                            "data": {
                                "id": "searchonly",
                                "title": "Spreadsheet workaround pain",
                                "selftext": "Still doing this manually",
                                "url": "https://reddit.com/searchonly",
                                "score": 12,
                                "permalink": "/r/python/comments/searchonly/search/",
                            }
                        },
                    ]
                }
            },
        )
    )

    scraper = RedditScraper(
        client_id="",
        client_secret="",
        user_agent="test/1.0",
        top_comments_limit=0,
        feed_mix=["top"],
        search_queries=["spreadsheet workaround"],
    )
    posts = await scraper._fetch_public_json("python", limit=5)

    assert {post.post_id for post in posts} == {"reddit:same", "reddit:searchonly"}
    by_id = {post.post_id: post for post in posts}
    assert by_id["reddit:same"].discovery_query == "spreadsheet workaround"
    assert by_id["reddit:searchonly"].discovery_query == "spreadsheet workaround"
    assert search_route.call_count == 1


async def test_fetch_public_json_treats_search_query_failure_as_optional():
    from unittest.mock import patch

    scraper = RedditScraper(
        client_id="",
        client_secret="",
        user_agent="test/1.0",
        top_comments_limit=0,
        feed_mix=["top"],
        search_queries=["spreadsheet workaround"],
    )

    async def payload_or_error(*, client, url, params, headers):
        if url.endswith("/search.json"):
            raise RuntimeError("search unavailable")
        return {
            "data": {
                "children": [
                    {
                        "data": {
                            "id": "toponly",
                            "title": "Top feed pain",
                            "selftext": "manual sync still breaks",
                            "url": "https://reddit.com/toponly",
                            "score": 8,
                            "permalink": "/r/python/comments/toponly/top-feed-pain/",
                        }
                    }
                ]
            }
        }

    with patch.object(scraper, "_request_json_with_retries", side_effect=payload_or_error):
        posts = await scraper._fetch_public_json("python", limit=10)

    assert [post.post_id for post in posts] == ["reddit:toponly"]


async def test_fetch_public_json_retries_transient_error_with_retry_after(respx_mock):
    from unittest.mock import AsyncMock, patch

    route = respx_mock.get("https://www.reddit.com/r/python/top.json").mock(
        side_effect=[
            httpx.Response(429, headers={"Retry-After": "0.2"}),
            httpx.Response(200, json={"data": {"children": []}}),
        ]
    )
    scraper = RedditScraper(
        client_id="",
        client_secret="",
        user_agent="test/1.0",
        retry_max_attempts=3,
        retry_base_delay=1.0,
    )

    with patch("scraper.asyncio.sleep", new=AsyncMock()) as sleep_mock:
        posts = await scraper._fetch_public_json("python", limit=10)

    assert posts == []
    assert route.call_count == 2
    sleep_mock.assert_awaited_once()
    assert sleep_mock.await_args.args[0] == 0.2


async def test_request_json_with_retries_retries_request_error_then_succeeds(respx_mock):
    from unittest.mock import AsyncMock, patch

    request = httpx.Request("GET", "https://www.reddit.com/r/python/top.json")
    route = respx_mock.get("https://www.reddit.com/r/python/top.json").mock(
        side_effect=[
            httpx.ConnectError("temporary network issue", request=request),
            httpx.Response(200, json={"data": {"children": []}}),
        ]
    )

    scraper = RedditScraper(client_id="", client_secret="", user_agent="test/1.0", retry_max_attempts=3)

    with patch("scraper.asyncio.sleep", new=AsyncMock()) as sleep_mock:
        posts = await scraper._fetch_public_json("python", limit=10)

    assert posts == []
    assert route.call_count == 2
    sleep_mock.assert_awaited_once()


async def test_fetch_public_json_requests_feeds_concurrently():
    from unittest.mock import patch

    scraper = RedditScraper(
        client_id="",
        client_secret="",
        user_agent="test/1.0",
        top_comments_limit=0,
        feed_mix=["top", "new", "rising"],
    )

    active_requests = 0
    max_active_requests = 0

    async def delayed_payload(*, client, url, params, headers):
        nonlocal active_requests, max_active_requests
        active_requests += 1
        max_active_requests = max(max_active_requests, active_requests)
        await asyncio.sleep(0.05)
        active_requests -= 1
        return {"data": {"children": []}}

    with patch.object(scraper, "_request_json_with_retries", side_effect=delayed_payload):
        posts = await scraper._fetch_public_json("python", limit=30)

    assert posts == []
    assert max_active_requests == 3


async def test_fetch_posts_falls_back_to_rss_when_public_json_is_blocked():
    from unittest.mock import AsyncMock, patch

    scraper = RedditScraper(client_id="", client_secret="", user_agent="test/1.0")
    fallback_posts = [
        Post(
            post_id="reddit:rss1",
            subreddit="python",
            title="RSS fallback post",
            body="manual workaround",
            url="https://reddit.com/r/python/comments/rss1/example/",
            score=11,
        )
    ]
    blocked_response = httpx.Response(
        403,
        request=httpx.Request("GET", "https://www.reddit.com/r/python/top.json"),
    )
    blocked_error = httpx.HTTPStatusError("blocked", request=blocked_response.request, response=blocked_response)

    with patch.object(scraper, "_fetch_public_json", new=AsyncMock(side_effect=blocked_error)):
        with patch.object(scraper, "_fetch_rss", new=AsyncMock(return_value=fallback_posts)) as rss_mock:
            posts = await scraper.fetch_posts("python", limit=5)

    rss_mock.assert_awaited_once_with("python", 5, "day")
    assert posts == fallback_posts


async def test_fetch_rss_merges_feed_and_search_results(respx_mock):
    feed_xml = """<?xml version='1.0' encoding='UTF-8'?>
    <feed xmlns='http://www.w3.org/2005/Atom'>
      <entry>
        <id>t3_same</id>
        <title>Need better alerts</title>
        <summary>Still doing manual checks</summary>
        <link href='https://reddit.com/r/python/comments/same/need-better-alerts/' />
      </entry>
    </feed>
    """
    search_xml = """<?xml version='1.0' encoding='UTF-8'?>
    <feed xmlns='http://www.w3.org/2005/Atom'>
      <entry>
        <id>t3_same</id>
        <title>Need better alerts</title>
        <summary>Still doing manual checks</summary>
        <link href='https://reddit.com/r/python/comments/same/need-better-alerts/' />
      </entry>
      <entry>
        <id>t3_rssonly</id>
        <title>Spreadsheet workaround pain</title>
        <summary>We export CSV files every week</summary>
        <link href='https://reddit.com/r/python/comments/rssonly/spreadsheet-workaround-pain/' />
      </entry>
    </feed>
    """

    respx_mock.get("https://old.reddit.com/r/python/top/.rss").mock(return_value=httpx.Response(200, text=feed_xml))
    search_route = respx_mock.get("https://old.reddit.com/r/python/search.rss").mock(
        return_value=httpx.Response(200, text=search_xml)
    )

    scraper = RedditScraper(
        client_id="",
        client_secret="",
        user_agent="test/1.0",
        top_comments_limit=0,
        feed_mix=["top"],
        search_queries=["spreadsheet workaround"],
    )

    posts = await scraper._fetch_rss("python", limit=5)

    assert {post.post_id for post in posts} == {"reddit:same", "reddit:rssonly"}
    by_id = {post.post_id: post for post in posts}
    assert by_id["reddit:same"].discovery_query == "spreadsheet workaround"
    assert by_id["reddit:rssonly"].discovery_query == "spreadsheet workaround"
    assert search_route.call_count == 1


async def test_fetch_rss_keeps_successful_feed_when_peer_feed_fails(respx_mock):
    feed_xml = """<?xml version='1.0' encoding='UTF-8'?>
    <feed xmlns='http://www.w3.org/2005/Atom'>
      <entry>
        <id>t3_rssnew</id>
        <title>New RSS pain</title>
        <summary>Manual checks still break</summary>
        <link href='https://reddit.com/r/python/comments/rssnew/new-rss-pain/' />
      </entry>
    </feed>
    """
    respx_mock.get("https://old.reddit.com/r/python/top/.rss").mock(return_value=httpx.Response(503))
    respx_mock.get("https://old.reddit.com/r/python/new/.rss").mock(return_value=httpx.Response(200, text=feed_xml))

    scraper = RedditScraper(
        client_id="",
        client_secret="",
        user_agent="test/1.0",
        top_comments_limit=0,
        feed_mix=["top", "new"],
    )

    posts = await scraper._fetch_rss("python", limit=5)

    assert [post.post_id for post in posts] == ["reddit:rssnew"]


async def test_fetch_rss_keeps_successful_feed_when_peer_feed_has_bad_xml(respx_mock):
    feed_xml = """<?xml version='1.0' encoding='UTF-8'?>
    <feed xmlns='http://www.w3.org/2005/Atom'>
      <entry>
        <id>t3_rssnew</id>
        <title>New RSS pain</title>
        <summary>Manual checks still break</summary>
        <link href='https://reddit.com/r/python/comments/rssnew/new-rss-pain/' />
      </entry>
    </feed>
    """
    respx_mock.get("https://old.reddit.com/r/python/top/.rss").mock(
        return_value=httpx.Response(200, text="<html>blocked</html")
    )
    respx_mock.get("https://old.reddit.com/r/python/new/.rss").mock(return_value=httpx.Response(200, text=feed_xml))

    scraper = RedditScraper(
        client_id="",
        client_secret="",
        user_agent="test/1.0",
        top_comments_limit=0,
        feed_mix=["top", "new"],
    )

    posts = await scraper._fetch_rss("python", limit=5)

    assert [post.post_id for post in posts] == ["reddit:rssnew"]


async def test_fetch_rss_keeps_feed_results_when_search_has_bad_xml(respx_mock):
    feed_xml = """<?xml version='1.0' encoding='UTF-8'?>
    <feed xmlns='http://www.w3.org/2005/Atom'>
      <entry>
        <id>t3_feed</id>
        <title>Feed pain</title>
        <summary>Manual checks still break</summary>
        <link href='https://reddit.com/r/python/comments/feed/feed-pain/' />
      </entry>
    </feed>
    """
    respx_mock.get("https://old.reddit.com/r/python/top/.rss").mock(return_value=httpx.Response(200, text=feed_xml))
    respx_mock.get("https://old.reddit.com/r/python/search.rss").mock(
        return_value=httpx.Response(200, text="<html>blocked</html")
    )

    scraper = RedditScraper(
        client_id="",
        client_secret="",
        user_agent="test/1.0",
        top_comments_limit=0,
        feed_mix=["top"],
        search_queries=["manual checks"],
    )

    posts = await scraper._fetch_rss("python", limit=5)

    assert [post.post_id for post in posts] == ["reddit:feed"]


async def test_fetch_oauth_json_requests_feeds_concurrently():
    from unittest.mock import patch

    scraper = RedditScraper(
        client_id="abc",
        client_secret="xyz",
        user_agent="test/1.0",
        top_comments_limit=0,
        feed_mix=["top", "new", "rising"],
    )

    active_requests = 0
    max_active_requests = 0

    async def delayed_payload(*, client, path, params):
        nonlocal active_requests, max_active_requests
        active_requests += 1
        max_active_requests = max(max_active_requests, active_requests)
        await asyncio.sleep(0.05)
        active_requests -= 1
        return {"data": {"children": []}}

    with patch.object(scraper, "_request_oauth_json", side_effect=delayed_payload):
        posts = await scraper._fetch_oauth_json("python", limit=30)

    assert posts == []
    assert max_active_requests == 3


async def test_fetch_oauth_json_keeps_successful_feed_when_peer_feed_fails():
    from unittest.mock import patch

    scraper = RedditScraper(
        client_id="abc",
        client_secret="xyz",
        user_agent="test/1.0",
        top_comments_limit=0,
        feed_mix=["top", "new"],
    )

    async def payload_or_error(*, client, path, params):
        if path.endswith("/top.json"):
            raise RuntimeError("top feed unavailable")
        return {
            "data": {
                "children": [
                    {
                        "data": {
                            "id": "oauthnew",
                            "title": "OAuth new pain",
                            "selftext": "manual sync still breaks",
                            "url": "https://reddit.com/oauthnew",
                            "score": 8,
                            "permalink": "/r/python/comments/oauthnew/oauth-new-pain/",
                        }
                    }
                ]
            }
        }

    with patch.object(scraper, "_request_oauth_json", side_effect=payload_or_error):
        posts = await scraper._fetch_oauth_json("python", limit=10)

    assert [post.post_id for post in posts] == ["reddit:oauthnew"]


async def test_fetch_full_thread_json_returns_flattened_comments(respx_mock):
    respx_mock.get("https://www.reddit.com/comments/abc1.json").mock(
        return_value=httpx.Response(
            200,
            json=[
                {},
                {
                    "data": {
                        "children": [
                            {
                                "kind": "t1",
                                "data": {
                                    "body": "parent",
                                    "replies": {
                                        "data": {
                                            "children": [
                                                {"kind": "t1", "data": {"body": "child"}}
                                            ]
                                        }
                                    },
                                },
                            }
                        ]
                    }
                },
            ],
        )
    )

    scraper = RedditScraper(client_id="", client_secret="", user_agent="test/1.0")
    comments = await scraper.fetch_full_thread("python", "abc1", max_comments=10)
    assert comments == ["parent", "child"]


async def test_fetch_top_comments_json_tolerates_malformed_listing(respx_mock):
    respx_mock.get("https://www.reddit.com/comments/abc1.json").mock(
        return_value=httpx.Response(200, json=[{}, "not-a-listing"])
    )

    scraper = RedditScraper(client_id="", client_secret="", user_agent="test/1.0")
    async with httpx.AsyncClient() as client:
        comments = await scraper._fetch_top_comments_json(
            client=client,
            post_id="abc1",
            limit=5,
        )

    assert comments == []


async def test_fetch_full_thread_json_skips_malformed_comment_nodes(respx_mock):
    respx_mock.get("https://www.reddit.com/comments/abc1.json").mock(
        return_value=httpx.Response(
            200,
            json=[
                {},
                {
                    "data": {
                        "children": [
                            "bad-child",
                            {"kind": "t1", "data": "bad-data"},
                            {
                                "kind": "t1",
                                "data": {
                                    "body": "parent",
                                    "replies": {
                                        "data": {
                                            "children": [
                                                "bad-reply",
                                                {"kind": "t1", "data": {"body": "child"}},
                                            ]
                                        }
                                    },
                                },
                            },
                        ]
                    }
                },
            ],
        )
    )

    scraper = RedditScraper(client_id="", client_secret="", user_agent="test/1.0")
    comments = await scraper.fetch_full_thread("python", "abc1", max_comments=10)

    assert comments == ["parent", "child"]


async def test_post_id_helpers_and_append_comments():
    scraper = RedditScraper(client_id="", client_secret="", user_agent="test/1.0")
    assert scraper._external_post_id("abc") == "reddit:abc"
    assert scraper._external_post_id("reddit:abc") == "reddit:abc"
    assert scraper._raw_post_id("reddit:abc") == "abc"
    assert scraper._raw_post_id("abc") == "abc"
    merged = scraper._append_comments("body", ["c1", "c2"])
    assert "Top comments:" in merged
    assert "- c1" in merged

