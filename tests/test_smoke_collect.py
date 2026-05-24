from __future__ import annotations

from scraper import Post


def _post(post_id: str = "reddit:abc") -> Post:
    return Post(
        post_id=post_id,
        subreddit="python",
        title="A painful manual workflow",
        body="",
        url="https://example.com/post",
        score=42,
        source="reddit",
    )


async def test_run_smoke_fetches_reddit_without_llm_or_writes(monkeypatch):
    import smoke_collect

    class FakeRedditScraper:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        async def fetch_posts(self, subreddit: str, limit: int = 100, timeframe: str = "day"):
            assert subreddit == "python"
            assert limit == 2
            assert timeframe == "day"
            return [_post()]

    monkeypatch.setattr(smoke_collect, "RedditScraper", FakeRedditScraper)

    exit_code, payload = await smoke_collect.run_smoke(["--source", "reddit", "--subreddit", "python", "--limit", "2"])

    assert exit_code == 0
    assert payload["ok"] is True
    assert payload["side_effects"] == "none: no LLM, Telegram, database, or export writes"
    assert payload["sources"][0]["source"] == "reddit"
    assert payload["sources"][0]["post_count"] == 1
    assert payload["sources"][0]["preview"][0]["post_id"] == "reddit:abc"


async def test_run_smoke_reports_source_exceptions(monkeypatch):
    import smoke_collect

    class FailingRedditScraper:
        def __init__(self, **kwargs):
            pass

        async def fetch_posts(self, subreddit: str, limit: int = 100, timeframe: str = "day"):
            raise RuntimeError("network unavailable")

    monkeypatch.setattr(smoke_collect, "RedditScraper", FailingRedditScraper)

    exit_code, payload = await smoke_collect.run_smoke(["--source", "reddit"])

    assert exit_code == 1
    assert payload["ok"] is False
    assert payload["errors"] == [{"source": "reddit", "reason": "exception", "error": "network unavailable"}]


async def test_run_smoke_require_posts_fails_empty_completed_source(monkeypatch):
    import smoke_collect

    class EmptyHackerNewsScraper:
        def __init__(self, user_agent: str):
            self.user_agent = user_agent

        async def fetch_posts(self, *, keywords: list[str], lookback_hours: int = 72, max_posts: int = 100):
            assert keywords == ["manual process"]
            assert max_posts == 3
            return []

    monkeypatch.setattr(smoke_collect, "HackerNewsScraper", EmptyHackerNewsScraper)

    exit_code, payload = await smoke_collect.run_smoke(
        ["--source", "hn", "--limit", "3", "--hn-keyword", "manual process", "--require-posts"]
    )

    assert exit_code == 2
    assert payload["ok"] is False
    assert payload["sources"][0]["post_count"] == 0
    assert payload["errors"] == [{"source": "hn", "reason": "empty", "error": "source returned zero posts"}]


async def test_run_smoke_all_sources_includes_review_target_count(monkeypatch):
    import smoke_collect

    class FakeRedditScraper:
        def __init__(self, **kwargs):
            pass

        async def fetch_posts(self, subreddit: str, limit: int = 100, timeframe: str = "day"):
            return [_post("reddit:one")]

    class FakeHackerNewsScraper:
        def __init__(self, user_agent: str):
            pass

        async def fetch_posts(self, *, keywords: list[str], lookback_hours: int = 72, max_posts: int = 100):
            return [_post("hn:one")]

    class FakeReviewScraper:
        def __init__(self, user_agent: str):
            pass

        async def fetch_many_targets(self, *, targets, max_per_target: int):
            assert len(targets) == 1
            return [_post("review:g2:test:one")]

    monkeypatch.setenv(
        "REVIEW_TARGETS_JSON",
        '[{"site":"g2","name":"Example CRM","url":"https://example.com/reviews","enabled":true}]',
    )
    monkeypatch.setattr(smoke_collect, "RedditScraper", FakeRedditScraper)
    monkeypatch.setattr(smoke_collect, "HackerNewsScraper", FakeHackerNewsScraper)
    monkeypatch.setattr(smoke_collect, "ReviewScraper", FakeReviewScraper)

    exit_code, payload = await smoke_collect.run_smoke(["--source", "all", "--limit", "1"])

    assert exit_code == 0
    assert [source["source"] for source in payload["sources"]] == ["reddit", "hn", "reviews"]
    assert payload["sources"][2]["targets_configured"] == 1
