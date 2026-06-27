from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
import sys
from dataclasses import dataclass
from typing import Any, Sequence

from dotenv import load_dotenv

from scraper import Post, RedditScraper
from scraper_hn import HackerNewsScraper
from scraper_reviews import ReviewScraper, ReviewTarget
from url_safety import is_public_http_url


DEFAULT_HN_KEYWORDS = ["internal tool", "frustrating", "we built our own", "manual process"]
ALLOWED_REDDIT_FEEDS = {"new", "rising", "top"}
TRUE_VALUES = {"1", "true", "on", "yes"}
FALSE_VALUES = {"0", "false", "off", "no"}


@dataclass(frozen=True)
class SourceSmokeConfig:
    reddit_client_id: str
    reddit_client_secret: str
    reddit_user_agent: str
    scraper_top_comments: int
    scraper_comment_fetch_concurrency: int
    scraper_retry_max_attempts: int
    scraper_retry_base_delay: float
    scraper_max_response_bytes: int
    scraper_feed_mix: list[str]
    scraper_search_queries: list[str]
    hn_keywords: list[str]
    hn_lookback_hours: int
    hn_max_response_bytes: int
    review_targets: list[ReviewTarget]
    reviews_max_per_target: int
    reviews_max_html_bytes: int


def _json_list_env(name: str, default: list[Any]) -> list[Any]:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{name} must be a valid JSON array") from exc
    if not isinstance(parsed, list):
        raise ValueError(f"{name} must be a JSON array")
    return parsed


def _env_int(name: str, default: int, minimum: int) -> int:
    raw = os.getenv(name, str(default))
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc
    if value < minimum:
        raise ValueError(f"{name} must be at least {minimum}")
    return value


def _env_float(name: str, default: float, minimum: float) -> float:
    raw = os.getenv(name, str(default))
    try:
        value = float(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be a number") from exc
    if not math.isfinite(value):
        raise ValueError(f"{name} must be finite")
    if value < minimum:
        raise ValueError(f"{name} must be at least {minimum:g}")
    return value


def _bool_value(name: str, raw: Any) -> bool:
    value = str(raw).strip().lower()
    if value in TRUE_VALUES:
        return True
    if value in FALSE_VALUES:
        return False
    raise ValueError(f"{name} must be a boolean: 1/0, true/false, on/off, or yes/no")


def _build_review_targets(raw_targets: list[Any]) -> list[ReviewTarget]:
    targets: list[ReviewTarget] = []
    for raw in raw_targets:
        if not isinstance(raw, dict):
            continue
        site = str(raw.get("site") or "").strip()
        name = str(raw.get("name") or "").strip()
        url = str(raw.get("url") or "").strip()
        if not site or not name or not url:
            continue
        enabled = _bool_value("REVIEW_TARGETS_JSON target enabled", raw.get("enabled", "1"))
        if enabled and not is_public_http_url(url):
            raise ValueError("REVIEW_TARGETS_JSON enabled target URLs must be public http or https URLs")
        targets.append(ReviewTarget(site=site, name=name, url=url, enabled=enabled))
    return targets


def load_source_smoke_config() -> SourceSmokeConfig:
    load_dotenv()
    scraper_feed_mix = [
        str(feed).strip().lower()
        for feed in _json_list_env("SCRAPER_FEED_MIX_JSON", ["new", "rising", "top"])
        if str(feed).strip()
    ]
    invalid_feeds = [feed for feed in scraper_feed_mix if feed not in ALLOWED_REDDIT_FEEDS]
    if not scraper_feed_mix or invalid_feeds:
        allowed = ", ".join(sorted(ALLOWED_REDDIT_FEEDS))
        raise ValueError(f"SCRAPER_FEED_MIX_JSON must contain only supported feeds: {allowed}")
    scraper_search_queries = [
        str(query).strip()
        for query in _json_list_env("SCRAPER_SEARCH_QUERIES_JSON", [])
        if str(query).strip()
    ]
    hn_keywords = [
        str(keyword).strip()
        for keyword in _json_list_env("HN_KEYWORDS_JSON", DEFAULT_HN_KEYWORDS)
        if str(keyword).strip()
    ]
    if os.getenv("HN_KEYWORDS_JSON") is not None and not hn_keywords:
        raise ValueError("HN_KEYWORDS_JSON must contain at least one non-empty keyword")
    return SourceSmokeConfig(
        reddit_client_id=os.getenv("REDDIT_CLIENT_ID", ""),
        reddit_client_secret=os.getenv("REDDIT_CLIENT_SECRET", ""),
        reddit_user_agent=os.getenv("REDDIT_USER_AGENT", "pain_finder/1.0"),
        scraper_top_comments=_env_int("SCRAPER_TOP_COMMENTS", 5, 0),
        scraper_comment_fetch_concurrency=_env_int("SCRAPER_COMMENT_FETCH_CONCURRENCY", 8, 1),
        scraper_retry_max_attempts=_env_int("SCRAPER_RETRY_MAX_ATTEMPTS", 5, 1),
        scraper_retry_base_delay=_env_float("SCRAPER_RETRY_BASE_DELAY", 1.0, 0.0),
        scraper_max_response_bytes=_env_int("SCRAPER_MAX_RESPONSE_BYTES", 5_000_000, 1024),
        scraper_feed_mix=scraper_feed_mix,
        scraper_search_queries=scraper_search_queries,
        hn_keywords=hn_keywords,
        hn_lookback_hours=_env_int("HN_LOOKBACK_HOURS", 72, 1),
        hn_max_response_bytes=_env_int("HN_MAX_RESPONSE_BYTES", 2_000_000, 1024),
        review_targets=_build_review_targets(_json_list_env("REVIEW_TARGETS_JSON", [])),
        reviews_max_per_target=_env_int("REVIEWS_MAX_PER_TARGET", 30, 1),
        reviews_max_html_bytes=_env_int("REVIEWS_MAX_HTML_BYTES", 2_000_000, 1024),
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Read-only source smoke check for operator readiness validation.\n"
            "Does not call LLMs, Telegram, or write the DB."
        ),
        epilog=(
            "Examples:\n"
            "  python smoke_collect.py --source reddit --subreddit python --limit 5\n"
            "  python smoke_collect.py --source all --limit 1 --require-posts"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--source", choices=("reddit", "hn", "reviews", "all"), default="reddit")
    parser.add_argument("--subreddit", default="python", help="Subreddit for the Reddit smoke check.")
    parser.add_argument("--limit", type=int, default=5, help="Maximum posts to fetch per source.")
    parser.add_argument(
        "--hn-keyword",
        action="append",
        default=[],
        help="HN keyword to query. Can be repeated; defaults to HN_KEYWORDS_JSON.",
    )
    parser.add_argument(
        "--require-posts",
        action="store_true",
        help="Fail closed when a requested source returns zero posts; use for readiness gates and CI smoke coverage.",
    )
    return parser


def _post_preview(post: Post) -> dict[str, Any]:
    return {
        "post_id": post.post_id,
        "source": post.source,
        "subreddit": post.subreddit,
        "title": post.title[:160],
        "score": post.score,
        "url": post.url,
        "source_created_at": post.source_created_at,
    }


async def _fetch_reddit(config: SourceSmokeConfig, *, subreddit: str, limit: int) -> list[Post]:
    scraper = RedditScraper(
        client_id=config.reddit_client_id,
        client_secret=config.reddit_client_secret,
        user_agent=config.reddit_user_agent,
        top_comments_limit=config.scraper_top_comments,
        comment_fetch_concurrency=config.scraper_comment_fetch_concurrency,
        retry_max_attempts=config.scraper_retry_max_attempts,
        retry_base_delay=config.scraper_retry_base_delay,
        feed_mix=config.scraper_feed_mix,
        search_queries=config.scraper_search_queries,
        max_response_bytes=config.scraper_max_response_bytes,
    )
    return await scraper.fetch_posts(subreddit, limit=limit)


async def _fetch_hn(config: SourceSmokeConfig, *, keywords: list[str], limit: int) -> list[Post]:
    scraper = HackerNewsScraper(user_agent=config.reddit_user_agent, max_response_bytes=config.hn_max_response_bytes)
    active_keywords = keywords or config.hn_keywords or DEFAULT_HN_KEYWORDS
    return await scraper.fetch_posts(
        keywords=active_keywords,
        lookback_hours=config.hn_lookback_hours,
        max_posts=limit,
    )


async def _fetch_reviews(config: SourceSmokeConfig, *, limit: int) -> list[Post]:
    if not any(target.enabled for target in config.review_targets):
        return []
    scraper = ReviewScraper(user_agent=config.reddit_user_agent, max_html_bytes=config.reviews_max_html_bytes)
    return await scraper.fetch_many_targets(
        targets=config.review_targets,
        max_per_target=min(limit, max(1, config.reviews_max_per_target)),
        max_total=limit,
    )


async def run_smoke(argv: Sequence[str] | None = None) -> tuple[int, dict[str, Any]]:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.limit < 1:
        return (
            1,
            {
                "ok": False,
                "side_effects": "none: no LLM, Telegram, database, or export writes",
                "sources": [],
                "errors": [{"source": "config", "reason": "exception", "error": "--limit must be at least 1"}],
            },
        )
    limit = min(args.limit, 100)
    try:
        config = load_source_smoke_config()
    except Exception as exc:
        return (
            1,
            {
                "ok": False,
                "side_effects": "none: no LLM, Telegram, database, or export writes",
                "sources": [],
                "errors": [{"source": "config", "reason": "exception", "error": str(exc)}],
            },
        )
    sources = ["reddit", "hn", "reviews"] if args.source == "all" else [args.source]
    results: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []

    for source in sources:
        try:
            if source == "reddit":
                posts = await _fetch_reddit(config, subreddit=args.subreddit, limit=limit)
                context: dict[str, Any] = {"subreddit": args.subreddit}
            elif source == "hn":
                keywords = [keyword.strip() for keyword in args.hn_keyword if keyword.strip()]
                posts = await _fetch_hn(config, keywords=keywords, limit=limit)
                context = {"keywords": keywords or config.hn_keywords or DEFAULT_HN_KEYWORDS}
            else:
                enabled_review_target_count = sum(1 for target in config.review_targets if target.enabled)
                if enabled_review_target_count == 0:
                    errors.append(
                        {
                            "source": "reviews",
                            "reason": "config",
                            "error": "REVIEW_TARGETS_JSON must contain at least one enabled review target for reviews smoke",
                        }
                    )
                    continue
                posts = await _fetch_reviews(config, limit=limit)
                context = {"targets_configured": enabled_review_target_count}
        except Exception as exc:
            errors.append({"source": source, "reason": "exception", "error": str(exc)})
            continue

        preview = [_post_preview(post) for post in posts[: min(5, limit)]]
        result = {
            "source": source,
            "ok": True,
            "post_count": len(posts),
            "preview": preview,
            **context,
        }
        results.append(result)
        if args.require_posts and not posts:
            errors.append({"source": source, "reason": "empty", "error": "source returned zero posts"})

    exit_code = 0
    if errors:
        exit_code = 2 if all(error["reason"] == "empty" for error in errors) else 1

    return (
        exit_code,
        {
            "ok": exit_code == 0,
            "side_effects": "none: no LLM, Telegram, database, or export writes",
            "sources": results,
            "errors": errors,
        },
    )


def main(argv: Sequence[str] | None = None) -> int:
    exit_code, payload = asyncio.run(run_smoke(argv))
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
