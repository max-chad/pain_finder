import asyncio
import html
import json
import logging
import math
import random
import re
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any

import httpx

logger = logging.getLogger(__name__)
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}
ALLOWED_FEEDS = {"top", "new", "rising"}
DEFAULT_FEEDS = ("top",)
MAX_REDDIT_RESPONSE_BYTES = 5_000_000
ATOM_NS = {"atom": "http://www.w3.org/2005/Atom"}
HTML_TAG_RE = re.compile(r"<[^>]+>")
REDDIT_COMMENT_PATH_RE = re.compile(r"/comments/([A-Za-z0-9_]+)/")
SUBREDDIT_RE = re.compile(r"^[A-Za-z0-9_]{2,21}$")


@dataclass
class Post:
    post_id: str
    subreddit: str
    title: str
    body: str
    url: str
    score: int
    permalink: str = ""
    top_comments: list[str] = field(default_factory=list)
    source: str = "reddit"
    discovery_query: str = ""
    source_created_at: str | None = None
    source_created_ts: int | None = None
    author_name: str | None = None


class RedditScraper:
    def __init__(
        self,
        client_id: str,
        client_secret: str,
        user_agent: str,
        top_comments_limit: int = 5,
        comment_fetch_concurrency: int = 8,
        retry_max_attempts: int = 5,
        retry_base_delay: float = 1.0,
        feed_mix: list[str] | tuple[str, ...] | None = None,
        search_queries: list[str] | tuple[str, ...] | None = None,
        max_response_bytes: int = MAX_REDDIT_RESPONSE_BYTES,
    ):
        self.client_id = client_id
        self.client_secret = client_secret
        self.user_agent = user_agent
        self.top_comments_limit = max(0, top_comments_limit)
        self.comment_fetch_concurrency = max(1, comment_fetch_concurrency)
        self.retry_max_attempts = max(1, retry_max_attempts)
        self.retry_base_delay = max(0.1, retry_base_delay)
        self.max_response_bytes = max(1, max_response_bytes)
        self._use_praw = bool(client_id and client_secret)
        self.feed_mix = self._normalize_feeds(feed_mix)
        self.search_queries = self._normalize_search_queries(search_queries)
        self._oauth_access_token: str = ""
        self._oauth_token_expires_at = 0.0

    async def fetch_posts(self, subreddit: str, limit: int = 100, timeframe: str = "day") -> list[Post]:
        subreddit = self._validate_subreddit(subreddit)
        if self._use_praw:
            try:
                return await self._fetch_praw(subreddit, limit, timeframe)
            except Exception as e:
                logger.warning("PRAW failed (%s), falling back to OAuth JSON", e)
            try:
                return await self._fetch_oauth_json(subreddit, limit, timeframe)
            except Exception as e:
                logger.warning("OAuth JSON failed (%s), falling back to public JSON", e)
        try:
            return await self._fetch_public_json(subreddit, limit, timeframe)
        except Exception as e:
            logger.warning("Public JSON failed (%s), falling back to RSS", e)
            return await self._fetch_rss(subreddit, limit, timeframe)

    async def fetch_full_thread(
        self,
        subreddit: str,
        post_id: str,
        max_comments: int = 250,
    ) -> list[str]:
        subreddit = self._validate_subreddit(subreddit)
        max_comments = max(1, max_comments)
        if self._use_praw:
            try:
                return await self._fetch_full_thread_praw(subreddit, post_id, max_comments)
            except Exception as e:
                logger.warning("PRAW full thread failed (%s), trying OAuth JSON", e)
            try:
                return await self._fetch_full_thread_oauth(post_id, max_comments)
            except Exception as e:
                logger.warning("OAuth full thread failed (%s), using public JSON fallback", e)
        return await self._fetch_full_thread_json(post_id, max_comments)

    @staticmethod
    def _external_post_id(raw_id: str) -> str:
        if raw_id.startswith("reddit:"):
            return raw_id
        return f"reddit:{raw_id}"

    @staticmethod
    def _raw_post_id(post_id: str) -> str:
        if ":" in post_id:
            return post_id.split(":", 1)[1]
        return post_id

    @staticmethod
    def _validate_subreddit(raw: str) -> str:
        subreddit = str(raw or "").strip()
        if not SUBREDDIT_RE.fullmatch(subreddit):
            raise ValueError("Invalid subreddit. Use letters, numbers, and underscores only.")
        return subreddit.lower()

    @staticmethod
    def _normalize_feeds(feed_mix: list[str] | tuple[str, ...] | None) -> list[str]:
        if not feed_mix:
            return list(DEFAULT_FEEDS)

        normalized: list[str] = []
        seen: set[str] = set()
        for raw in feed_mix:
            feed = str(raw).strip().lower()
            if feed not in ALLOWED_FEEDS or feed in seen:
                continue
            seen.add(feed)
            normalized.append(feed)
        return normalized or list(DEFAULT_FEEDS)

    @staticmethod
    def _normalize_search_queries(search_queries: list[str] | tuple[str, ...] | None) -> list[str]:
        if not search_queries:
            return []

        normalized: list[str] = []
        seen: set[str] = set()
        for raw in search_queries:
            query = str(raw).strip()
            if not query:
                continue
            lowered = query.lower()
            if lowered in seen:
                continue
            seen.add(lowered)
            normalized.append(query)
        return normalized

    def _iter_search_requests(self, *, limit: int) -> list[tuple[str, dict[str, Any]]]:
        if not self.search_queries:
            return []
        per_query_limit = max(1, min(100, math.ceil(max(1, limit) / max(1, len(self.search_queries)))))
        return [
            (
                query,
                {
                    "q": query,
                    "restrict_sr": "on",
                    "sort": "relevance",
                    "limit": per_query_limit,
                    "raw_json": 1,
                },
            )
            for query in self.search_queries
        ]

    @staticmethod
    def _build_post(subreddit: str, post_data: dict[str, Any], *, discovery_query: str = "") -> Post | None:
        post_id = post_data.get("id")
        if not post_id:
            return None
        prefixed_post_id = RedditScraper._external_post_id(post_id)
        permalink = post_data.get("permalink", "")
        if permalink and not permalink.startswith("http"):
            full_url = f"https://reddit.com{permalink}"
        else:
            full_url = post_data.get("url", "")
        source_created_at, source_created_ts = RedditScraper._normalize_source_timestamp(post_data.get("created_utc"))
        return Post(
            post_id=prefixed_post_id,
            subreddit=subreddit,
            title=post_data.get("title", ""),
            body=post_data.get("selftext", ""),
            url=full_url,
            score=RedditScraper._safe_int(post_data.get("score", 0)),
            permalink=permalink,
            discovery_query=discovery_query,
            source_created_at=source_created_at,
            source_created_ts=source_created_ts,
            author_name=(post_data.get("author") or None),
        )

    @staticmethod
    def _normalize_source_timestamp(raw_ts: Any) -> tuple[str | None, int | None]:
        if raw_ts in {None, ""}:
            return None, None
        try:
            ts = int(float(raw_ts))
        except (TypeError, ValueError):
            return None, None
        if ts <= 0:
            return None, None
        dt = datetime.fromtimestamp(ts, UTC)
        return dt.isoformat(), ts

    @staticmethod
    def _safe_int(raw_value: Any, default: int = 0) -> int:
        try:
            return int(raw_value or default)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _decode_response_content(response: httpx.Response) -> str:
        return response.content.decode(response.encoding or "utf-8", errors="replace")

    async def _request_with_response_limit(
        self,
        *,
        client: httpx.AsyncClient,
        method: str,
        url: str,
        params: dict[str, Any] | None = None,
        data: dict[str, Any] | None = None,
        auth: tuple[str, str] | None = None,
        headers: dict[str, str] | None = None,
        timeout: float = 20,
    ) -> httpx.Response:
        async with client.stream(
            method,
            url,
            params=params,
            data=data,
            auth=auth,
            headers=headers,
            timeout=timeout,
        ) as response:
            body = bytearray()
            async for chunk in response.aiter_bytes():
                body.extend(chunk)
                if len(body) > self.max_response_bytes:
                    raise RuntimeError(f"Reddit response exceeded {self.max_response_bytes} bytes")
            return httpx.Response(
                response.status_code,
                headers=response.headers,
                content=bytes(body),
                request=response.request,
                extensions=response.extensions,
            )

    @staticmethod
    def _listing_children(payload: Any, index: int = 1) -> list[Any]:
        if not isinstance(payload, list) or len(payload) <= index:
            return []
        listing = payload[index]
        if not isinstance(listing, dict):
            return []
        data = listing.get("data", {})
        if not isinstance(data, dict):
            return []
        children = data.get("children", [])
        return children if isinstance(children, list) else []

    @staticmethod
    def _parse_datetime_text(raw_text: str) -> tuple[str | None, int | None]:
        text = (raw_text or "").strip()
        if not text:
            return None, None
        try:
            dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            try:
                dt = parsedate_to_datetime(text)
            except (TypeError, ValueError):
                return None, None
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        else:
            dt = dt.astimezone(UTC)
        return dt.isoformat(), int(dt.timestamp())

    @staticmethod
    def _merge_post(posts_by_id: dict[str, Post], post: Post) -> None:
        existing = posts_by_id.get(post.post_id)
        if existing is None:
            posts_by_id[post.post_id] = post
            return
        if post.score > existing.score:
            existing.score = post.score
        if post.discovery_query and not existing.discovery_query:
            existing.discovery_query = post.discovery_query
        if not existing.permalink and post.permalink:
            existing.permalink = post.permalink
        if not existing.url and post.url:
            existing.url = post.url
        if post.source_created_ts and (
            existing.source_created_ts is None or post.source_created_ts < existing.source_created_ts
        ):
            existing.source_created_ts = post.source_created_ts
            existing.source_created_at = post.source_created_at
        elif existing.source_created_at is None and post.source_created_at is not None:
            existing.source_created_at = post.source_created_at
        if not existing.author_name and post.author_name:
            existing.author_name = post.author_name

    @staticmethod
    def _rss_feed_url(subreddit: str, feed: str) -> str:
        if feed == "top":
            return f"https://old.reddit.com/r/{subreddit}/top/.rss"
        if feed == "new":
            return f"https://old.reddit.com/r/{subreddit}/new/.rss"
        return f"https://old.reddit.com/r/{subreddit}/rising/.rss"

    @staticmethod
    def _sanitize_rss_text(raw: str) -> str:
        if not raw:
            return ""
        cleaned = HTML_TAG_RE.sub(" ", raw)
        cleaned = html.unescape(cleaned)
        return " ".join(cleaned.split())

    @staticmethod
    def _extract_rss_post_id(entry_id: str, link: str) -> str:
        value = (entry_id or "").strip()
        if value.startswith("t3_"):
            return value[3:]
        match = REDDIT_COMMENT_PATH_RE.search(link or "")
        if match:
            return match.group(1)
        if value:
            return value.rsplit("/", 1)[-1]
        return ""

    @classmethod
    def _parse_rss_entries(cls, subreddit: str, xml_text: str, *, discovery_query: str = "") -> list[Post]:
        root = ET.fromstring(xml_text)
        posts: list[Post] = []
        for entry in root.findall("atom:entry", ATOM_NS):
            entry_id = entry.findtext("atom:id", default="", namespaces=ATOM_NS)
            title = cls._sanitize_rss_text(entry.findtext("atom:title", default="", namespaces=ATOM_NS))
            summary = cls._sanitize_rss_text(entry.findtext("atom:summary", default="", namespaces=ATOM_NS))
            content = cls._sanitize_rss_text(entry.findtext("atom:content", default="", namespaces=ATOM_NS))
            updated = entry.findtext("atom:updated", default="", namespaces=ATOM_NS)
            published = entry.findtext("atom:published", default="", namespaces=ATOM_NS)
            source_created_at, source_created_ts = cls._parse_datetime_text(published or updated)
            author_name = cls._sanitize_rss_text(entry.findtext("atom:author/atom:name", default="", namespaces=ATOM_NS)) or None
            link = ""
            permalink = ""
            for link_node in entry.findall("atom:link", ATOM_NS):
                href = (link_node.attrib.get("href") or "").strip()
                if href:
                    link = href
                    if href.startswith("https://www.reddit.com"):
                        link = href.replace("https://www.reddit.com", "https://reddit.com", 1)
                    elif href.startswith("https://old.reddit.com"):
                        link = href.replace("https://old.reddit.com", "https://reddit.com", 1)
                    if link.startswith("https://reddit.com/r/"):
                        permalink = link.removeprefix("https://reddit.com")
                    break
            raw_post_id = cls._extract_rss_post_id(entry_id, link)
            if not raw_post_id:
                continue
            body = summary or content
            posts.append(
                Post(
                    post_id=cls._external_post_id(raw_post_id),
                    subreddit=subreddit,
                    title=title,
                    body=body,
                    url=link,
                    score=0,
                    permalink=permalink,
                    discovery_query=discovery_query,
                    source_created_at=source_created_at,
                    source_created_ts=source_created_ts,
                    author_name=author_name,
                )
            )
        return posts

    def _rss_request_params(self, params: dict[str, Any]) -> dict[str, Any]:
        filtered: dict[str, Any] = {}
        for key, value in params.items():
            if key in {"raw_json", "limit"}:
                continue
            filtered[key] = value
        return filtered

    def _iter_feed_requests(self, *, limit: int, timeframe: str) -> list[tuple[str, dict[str, Any]]]:
        per_feed_limit = max(1, min(100, math.ceil(max(1, limit) / max(1, len(self.feed_mix)))))
        requests: list[tuple[str, dict[str, Any]]] = []
        for feed in self.feed_mix:
            params: dict[str, Any] = {"limit": per_feed_limit, "raw_json": 1}
            if feed == "top":
                params["t"] = timeframe
            requests.append((feed, params))
        return requests

    async def _fetch_praw(self, subreddit: str, limit: int, timeframe: str) -> list[Post]:
        import praw

        def _sync_fetch() -> list[Post]:
            reddit = praw.Reddit(
                client_id=self.client_id,
                client_secret=self.client_secret,
                user_agent=self.user_agent,
            )
            posts_by_id: dict[str, Post] = {}
            sub = reddit.subreddit(subreddit)

            for feed, params in self._iter_feed_requests(limit=limit, timeframe=timeframe):
                feed_limit = int(params.get("limit", limit))
                if feed == "top":
                    iterator = sub.top(time_filter=timeframe, limit=feed_limit)
                elif feed == "new":
                    iterator = sub.new(limit=feed_limit)
                else:
                    iterator = sub.rising(limit=feed_limit)

                for submission in iterator:
                    top_comments: list[str] = []
                    if self.top_comments_limit > 0:
                        try:
                            submission.comment_sort = "top"
                            submission.comments.replace_more(limit=0)
                            for comment in submission.comments[: self.top_comments_limit]:
                                body = getattr(comment, "body", "")
                                if isinstance(body, str) and body.strip():
                                    top_comments.append(body.strip())
                        except Exception as e:
                            logger.debug("Unable to fetch top comments for %s: %s", submission.id, e)

                    body = self._append_comments(submission.selftext or "", top_comments)
                    source_created_at, source_created_ts = self._normalize_source_timestamp(getattr(submission, "created_utc", None))
                    post = Post(
                        post_id=self._external_post_id(submission.id),
                        subreddit=subreddit,
                        title=submission.title,
                        body=body,
                        url=f"https://reddit.com{submission.permalink}",
                        score=submission.score,
                        permalink=submission.permalink,
                        top_comments=top_comments,
                        source_created_at=source_created_at,
                        source_created_ts=source_created_ts,
                        author_name=str(getattr(submission, "author", "") or "") or None,
                    )
                    self._merge_post(posts_by_id, post)

            for query, params in self._iter_search_requests(limit=limit):
                search_limit = int(params.get("limit", limit))
                iterator = sub.search(
                    query,
                    sort="relevance",
                    time_filter=timeframe,
                    limit=search_limit,
                )
                for submission in iterator:
                    source_created_at, source_created_ts = self._normalize_source_timestamp(getattr(submission, "created_utc", None))
                    post = Post(
                        post_id=self._external_post_id(submission.id),
                        subreddit=subreddit,
                        title=submission.title,
                        body=submission.selftext or "",
                        url=f"https://reddit.com{submission.permalink}",
                        score=submission.score,
                        permalink=submission.permalink,
                        discovery_query=query,
                        source_created_at=source_created_at,
                        source_created_ts=source_created_ts,
                        author_name=str(getattr(submission, "author", "") or "") or None,
                    )
                    self._merge_post(posts_by_id, post)

            posts = sorted(posts_by_id.values(), key=lambda item: item.score, reverse=True)
            return posts[:limit]

        return await asyncio.to_thread(_sync_fetch)

    async def _fetch_public_json(self, subreddit: str, limit: int, timeframe: str = "day") -> list[Post]:
        headers = {"User-Agent": self.user_agent}

        async with httpx.AsyncClient() as client:
            posts_by_id: dict[str, Post] = {}
            feed_requests = self._iter_feed_requests(limit=limit, timeframe=timeframe)
            feed_error: Exception | None = None

            async def fetch_feed(feed: str, params: dict[str, Any]) -> Any:
                nonlocal feed_error
                url = f"https://www.reddit.com/r/{subreddit}/{feed}.json"
                try:
                    return await self._request_json_with_retries(
                        client=client,
                        url=url,
                        params=params,
                        headers=headers,
                    )
                except Exception as e:
                    feed_error = e
                    logger.warning("Reddit public feed failed for r/%s feed=%s: %s", subreddit, feed, e)
                    return None

            payloads = await asyncio.gather(*(fetch_feed(feed, params) for feed, params in feed_requests))
            if all(payload is None for payload in payloads) and feed_error is not None:
                raise feed_error

            for payload in payloads:
                if payload is None:
                    continue
                for child in payload.get("data", {}).get("children", []):
                    post = self._build_post(subreddit, child.get("data", {}))
                    if post is None:
                        continue
                    self._merge_post(posts_by_id, post)

            async def fetch_search(query: str, params: dict[str, Any]) -> Any:
                url = f"https://www.reddit.com/r/{subreddit}/search.json"
                try:
                    return await self._request_json_with_retries(
                        client=client,
                        url=url,
                        params=params,
                        headers=headers,
                    )
                except Exception as e:
                    logger.warning("Reddit public search failed for r/%s query=%r: %s", subreddit, query, e)
                    return None

            search_payloads = await asyncio.gather(
                *(fetch_search(query, params) for query, params in self._iter_search_requests(limit=limit))
            )
            for (query, _), payload in zip(self._iter_search_requests(limit=limit), search_payloads, strict=False):
                if payload is None:
                    continue
                for child in payload.get("data", {}).get("children", []):
                    post = self._build_post(subreddit, child.get("data", {}), discovery_query=query)
                    if post is None:
                        continue
                    self._merge_post(posts_by_id, post)

            base_posts = sorted(posts_by_id.values(), key=lambda item: item.score, reverse=True)[:limit]

            if self.top_comments_limit <= 0 or not base_posts:
                return base_posts

            semaphore = asyncio.Semaphore(self.comment_fetch_concurrency)

            async def hydrate_comments(post: Post) -> Post:
                async with semaphore:
                    comments = await self._fetch_top_comments_json(
                        client=client,
                        post_id=post.post_id,
                        limit=self.top_comments_limit,
                    )
                post.top_comments = comments
                post.body = self._append_comments(post.body, comments)
                return post

            hydrated = await asyncio.gather(*(hydrate_comments(post) for post in base_posts))
            return list(hydrated)

    async def _fetch_rss(self, subreddit: str, limit: int, timeframe: str = "day") -> list[Post]:
        headers = {"User-Agent": self.user_agent}

        async with httpx.AsyncClient() as client:
            posts_by_id: dict[str, Post] = {}
            feed_requests = self._iter_feed_requests(limit=limit, timeframe=timeframe)
            feed_error: Exception | None = None

            async def fetch_feed(feed: str, params: dict[str, Any]) -> str:
                nonlocal feed_error
                try:
                    response = await self._request_with_response_limit(
                        client=client,
                        method="GET",
                        url=self._rss_feed_url(subreddit, feed),
                        params=self._rss_request_params(params),
                        headers=headers,
                        timeout=20,
                    )
                    response.raise_for_status()
                    return self._decode_response_content(response)
                except Exception as e:
                    feed_error = e
                    logger.warning("RSS feed failed for r/%s feed=%s: %s", subreddit, feed, e)
                    return ""

            feed_payloads = await asyncio.gather(*(fetch_feed(feed, params) for feed, params in feed_requests))
            if all(not payload for payload in feed_payloads) and feed_error is not None:
                raise feed_error
            for payload in feed_payloads:
                if not payload:
                    continue
                try:
                    parsed_posts = self._parse_rss_entries(subreddit, payload)
                except ET.ParseError as e:
                    logger.warning("RSS parse failed for r/%s feed payload: %s", subreddit, e)
                    continue
                for post in parsed_posts:
                    self._merge_post(posts_by_id, post)

            async def fetch_search(query: str, params: dict[str, Any]) -> str | None:
                try:
                    response = await self._request_with_response_limit(
                        client=client,
                        method="GET",
                        url=f"https://old.reddit.com/r/{subreddit}/search.rss",
                        params=self._rss_request_params(params),
                        headers=headers,
                        timeout=20,
                    )
                    response.raise_for_status()
                    return self._decode_response_content(response)
                except Exception as e:
                    logger.warning("RSS search failed for r/%s query %r: %s", subreddit, query, e)
                    return None

            search_requests = self._iter_search_requests(limit=limit)
            search_payloads = await asyncio.gather(*(fetch_search(query, params) for query, params in search_requests))
            for (query, _), payload in zip(search_requests, search_payloads, strict=False):
                if not payload:
                    continue
                try:
                    parsed_posts = self._parse_rss_entries(subreddit, payload, discovery_query=query)
                except ET.ParseError as e:
                    logger.warning("RSS search parse failed for r/%s query %r: %s", subreddit, query, e)
                    continue
                for post in parsed_posts:
                    self._merge_post(posts_by_id, post)

            base_posts = sorted(posts_by_id.values(), key=lambda item: item.score, reverse=True)[:limit]
            if self.top_comments_limit <= 0 or not base_posts:
                return base_posts

            semaphore = asyncio.Semaphore(self.comment_fetch_concurrency)

            async def hydrate_comments(post: Post) -> Post:
                async with semaphore:
                    comments = await self._fetch_top_comments_json(
                        client=client,
                        post_id=post.post_id,
                        limit=self.top_comments_limit,
                    )
                post.top_comments = comments
                post.body = self._append_comments(post.body, comments)
                return post

            hydrated = await asyncio.gather(*(hydrate_comments(post) for post in base_posts))
            return list(hydrated)

    async def _fetch_oauth_json(self, subreddit: str, limit: int, timeframe: str = "day") -> list[Post]:
        async with httpx.AsyncClient() as client:
            posts_by_id: dict[str, Post] = {}
            feed_requests = self._iter_feed_requests(limit=limit, timeframe=timeframe)
            feed_error: Exception | None = None

            async def fetch_feed(feed: str, params: dict[str, Any]) -> Any:
                nonlocal feed_error
                try:
                    return await self._request_oauth_json(
                        client=client,
                        path=f"/r/{subreddit}/{feed}.json",
                        params=params,
                    )
                except Exception as e:
                    feed_error = e
                    logger.warning("Reddit OAuth feed failed for r/%s feed=%s: %s", subreddit, feed, e)
                    return None

            payloads = await asyncio.gather(*(fetch_feed(feed, params) for feed, params in feed_requests))
            if all(payload is None for payload in payloads) and feed_error is not None:
                raise feed_error

            for payload in payloads:
                if payload is None:
                    continue
                for child in payload.get("data", {}).get("children", []):
                    post = self._build_post(subreddit, child.get("data", {}))
                    if post is None:
                        continue
                    self._merge_post(posts_by_id, post)

            async def fetch_search(query: str, params: dict[str, Any]) -> Any:
                try:
                    return await self._request_oauth_json(
                        client=client,
                        path=f"/r/{subreddit}/search.json",
                        params=params,
                    )
                except Exception as e:
                    logger.warning("Reddit OAuth search failed for r/%s query=%r: %s", subreddit, query, e)
                    return None

            search_payloads = await asyncio.gather(
                *(fetch_search(query, params) for query, params in self._iter_search_requests(limit=limit))
            )
            for (query, _), payload in zip(self._iter_search_requests(limit=limit), search_payloads, strict=False):
                if payload is None:
                    continue
                for child in payload.get("data", {}).get("children", []):
                    post = self._build_post(subreddit, child.get("data", {}), discovery_query=query)
                    if post is None:
                        continue
                    self._merge_post(posts_by_id, post)

            base_posts = sorted(posts_by_id.values(), key=lambda item: item.score, reverse=True)[:limit]
            if self.top_comments_limit <= 0 or not base_posts:
                return base_posts

            semaphore = asyncio.Semaphore(self.comment_fetch_concurrency)

            async def hydrate_comments(post: Post) -> Post:
                async with semaphore:
                    comments = await self._fetch_top_comments_oauth(
                        client=client,
                        post_id=post.post_id,
                        limit=self.top_comments_limit,
                    )
                post.top_comments = comments
                post.body = self._append_comments(post.body, comments)
                return post

            hydrated = await asyncio.gather(*(hydrate_comments(post) for post in base_posts))
            return list(hydrated)

    async def _request_oauth_json(
        self,
        *,
        client: httpx.AsyncClient,
        path: str,
        params: dict[str, Any],
    ) -> Any:
        token = await self._get_oauth_token(client=client)
        headers = {
            "User-Agent": self.user_agent,
            "Authorization": f"bearer {token}",
        }
        try:
            return await self._request_json_with_retries(
                client=client,
                url=f"https://oauth.reddit.com{path}",
                params=params,
                headers=headers,
            )
        except httpx.HTTPStatusError as e:
            status_code = e.response.status_code if e.response else None
            if status_code != 401:
                raise
            self._oauth_access_token = ""
            self._oauth_token_expires_at = 0.0
            token = await self._get_oauth_token(client=client)
            headers["Authorization"] = f"bearer {token}"
            return await self._request_json_with_retries(
                client=client,
                url=f"https://oauth.reddit.com{path}",
                params=params,
                headers=headers,
            )

    async def _get_oauth_token(self, *, client: httpx.AsyncClient) -> str:
        if self._oauth_access_token and self._oauth_token_expires_at > time.time() + 30:
            return self._oauth_access_token

        response = await self._request_with_response_limit(
            client=client,
            method="POST",
            url="https://www.reddit.com/api/v1/access_token",
            data={"grant_type": "client_credentials"},
            auth=(self.client_id, self.client_secret),
            headers={"User-Agent": self.user_agent},
            timeout=20,
        )
        response.raise_for_status()
        payload = json.loads(self._decode_response_content(response))
        token = payload.get("access_token", "")
        if not token:
            raise RuntimeError("Reddit OAuth token response missing access_token")
        expires_in = int(payload.get("expires_in", 3600) or 3600)
        self._oauth_access_token = token
        self._oauth_token_expires_at = time.time() + max(60, expires_in)
        return token

    async def _fetch_top_comments_oauth(
        self,
        *,
        client: httpx.AsyncClient,
        post_id: str,
        limit: int,
    ) -> list[str]:
        raw_post_id = self._raw_post_id(post_id)
        params = {"limit": limit, "sort": "top", "raw_json": 1, "depth": 1}
        try:
            payload = await self._request_oauth_json(
                client=client,
                path=f"/comments/{raw_post_id}.json",
                params=params,
            )
        except Exception as e:
            logger.debug("Unable to fetch top comments via OAuth for %s: %s", post_id, e)
            return []

        comments_listing = self._listing_children(payload)
        comments: list[str] = []
        for child in comments_listing:
            if not isinstance(child, dict):
                continue
            if child.get("kind") != "t1":
                continue
            data = child.get("data", {})
            if not isinstance(data, dict):
                continue
            body = data.get("body", "")
            if isinstance(body, str) and body.strip():
                comments.append(body.strip())
            if len(comments) >= limit:
                break
        return comments

    async def _fetch_top_comments_json(
        self,
        *,
        client: httpx.AsyncClient,
        post_id: str,
        limit: int,
    ) -> list[str]:
        raw_post_id = self._raw_post_id(post_id)
        url = f"https://www.reddit.com/comments/{raw_post_id}.json"
        params = {"limit": limit, "sort": "top", "raw_json": 1, "depth": 1}
        headers = {"User-Agent": self.user_agent}
        try:
            payload = await self._request_json_with_retries(
                client=client,
                url=url,
                params=params,
                headers=headers,
            )
        except Exception as e:
            logger.debug("Unable to fetch top comments via JSON for %s: %s", post_id, e)
            return await self._fetch_comments_rss(client=client, post_id=post_id, limit=limit)

        comments_listing = self._listing_children(payload)
        comments: list[str] = []
        for child in comments_listing:
            if not isinstance(child, dict):
                continue
            if child.get("kind") != "t1":
                continue
            data = child.get("data", {})
            if not isinstance(data, dict):
                continue
            body = data.get("body", "")
            if isinstance(body, str) and body.strip():
                comments.append(body.strip())
            if len(comments) >= limit:
                break
        if comments:
            return comments
        return await self._fetch_comments_rss(client=client, post_id=post_id, limit=limit)

    async def _fetch_comments_rss(
        self,
        *,
        client: httpx.AsyncClient,
        post_id: str,
        limit: int,
    ) -> list[str]:
        raw_post_id = self._raw_post_id(post_id)
        try:
            response = await self._request_with_response_limit(
                client=client,
                method="GET",
                url=f"https://old.reddit.com/comments/{raw_post_id}/.rss",
                params={"limit": limit, "sort": "top"},
                headers={"User-Agent": self.user_agent},
                timeout=20,
            )
            response.raise_for_status()
            payload = self._decode_response_content(response)
        except Exception as e:
            logger.debug("Unable to fetch comments via RSS for %s: %s", post_id, e)
            return []

        try:
            root = ET.fromstring(payload)
        except ET.ParseError as e:
            logger.debug("Unable to parse comments RSS for %s: %s", post_id, e)
            return []

        comments: list[str] = []
        for entry in root.findall("atom:entry", ATOM_NS):
            entry_id = (entry.findtext("atom:id", default="", namespaces=ATOM_NS) or "").strip()
            if not entry_id.startswith("t1_"):
                continue
            content = entry.findtext("atom:content", default="", namespaces=ATOM_NS) or entry.findtext(
                "atom:summary",
                default="",
                namespaces=ATOM_NS,
            )
            text = " ".join(html.unescape(HTML_TAG_RE.sub(" ", content or "")).split())
            if text:
                comments.append(text)
            if len(comments) >= limit:
                break
        return comments

    async def _fetch_full_thread_oauth(self, post_id: str, max_comments: int) -> list[str]:
        raw_post_id = self._raw_post_id(post_id)
        params = {"limit": max_comments, "sort": "top", "raw_json": 1, "depth": 10}

        async with httpx.AsyncClient() as client:
            payload = await self._request_oauth_json(
                client=client,
                path=f"/comments/{raw_post_id}.json",
                params=params,
            )

        comment_nodes = self._listing_children(payload)
        comments: list[str] = []

        def walk(nodes: list[Any]) -> None:
            for node in nodes:
                if len(comments) >= max_comments:
                    return
                if not isinstance(node, dict):
                    continue
                if node.get("kind") != "t1":
                    continue
                data = node.get("data", {})
                if not isinstance(data, dict):
                    continue
                body = data.get("body", "")
                if isinstance(body, str) and body.strip():
                    comments.append(body.strip())
                replies = data.get("replies")
                if isinstance(replies, dict):
                    children = replies.get("data", {}).get("children", [])
                    if isinstance(children, list):
                        walk(children)

        walk(comment_nodes)
        return comments[:max_comments]

    async def _fetch_full_thread_json(self, post_id: str, max_comments: int) -> list[str]:
        raw_post_id = self._raw_post_id(post_id)
        url = f"https://www.reddit.com/comments/{raw_post_id}.json"
        params = {"limit": max_comments, "sort": "top", "raw_json": 1, "depth": 10}
        headers = {"User-Agent": self.user_agent}

        async with httpx.AsyncClient() as client:
            try:
                payload = await self._request_json_with_retries(
                    client=client,
                    url=url,
                    params=params,
                    headers=headers,
                )
            except Exception as e:
                logger.debug("Unable to fetch full thread via JSON for %s: %s", post_id, e)
                return await self._fetch_comments_rss(client=client, post_id=post_id, limit=max_comments)

        comment_nodes = self._listing_children(payload)
        comments: list[str] = []

        def walk(nodes: list[Any]) -> None:
            for node in nodes:
                if len(comments) >= max_comments:
                    return
                if not isinstance(node, dict):
                    continue
                if node.get("kind") != "t1":
                    continue
                data = node.get("data", {})
                if not isinstance(data, dict):
                    continue
                body = data.get("body", "")
                if isinstance(body, str) and body.strip():
                    comments.append(body.strip())
                replies = data.get("replies")
                if isinstance(replies, dict):
                    children = replies.get("data", {}).get("children", [])
                    if isinstance(children, list):
                        walk(children)

        walk(comment_nodes)
        return comments[:max_comments]

    async def _fetch_full_thread_praw(self, subreddit: str, post_id: str, max_comments: int) -> list[str]:
        import praw

        def _sync_fetch() -> list[str]:
            reddit = praw.Reddit(
                client_id=self.client_id,
                client_secret=self.client_secret,
                user_agent=self.user_agent,
            )
            submission = reddit.submission(id=self._raw_post_id(post_id))
            submission.comment_sort = "top"
            submission.comments.replace_more(limit=0)

            comments: list[str] = []
            for comment in submission.comments.list():
                body = getattr(comment, "body", "")
                if isinstance(body, str) and body.strip():
                    comments.append(body.strip())
                if len(comments) >= max_comments:
                    break
            return comments

        return await asyncio.to_thread(_sync_fetch)

    async def _request_json_with_retries(
        self,
        *,
        client: httpx.AsyncClient,
        url: str,
        params: dict[str, Any],
        headers: dict[str, str],
    ) -> Any:
        last_error: Exception | None = None

        for attempt in range(1, self.retry_max_attempts + 1):
            try:
                response = await self._request_with_response_limit(
                    client=client,
                    method="GET",
                    url=url,
                    params=params,
                    headers=headers,
                    timeout=20,
                )
                response.raise_for_status()
                return json.loads(self._decode_response_content(response))
            except httpx.HTTPStatusError as e:
                last_error = e
                status_code = e.response.status_code if e.response else None
                if status_code not in RETRYABLE_STATUS_CODES or attempt >= self.retry_max_attempts:
                    raise

                retry_after = e.response.headers.get("Retry-After") if e.response else None
                delay = self._compute_backoff_delay(attempt, retry_after=retry_after)
                logger.warning(
                    "Reddit HTTP %s attempt %d/%d for %s, retrying in %.2fs",
                    status_code,
                    attempt,
                    self.retry_max_attempts,
                    url,
                    delay,
                )
                await asyncio.sleep(delay)
            except httpx.RequestError as e:
                last_error = e
                if attempt >= self.retry_max_attempts:
                    raise
                delay = self._compute_backoff_delay(attempt)
                logger.warning(
                    "Reddit request error attempt %d/%d for %s: %s; retrying in %.2fs",
                    attempt,
                    self.retry_max_attempts,
                    url,
                    e,
                    delay,
                )
                await asyncio.sleep(delay)

        if last_error is not None:
            raise last_error
        raise RuntimeError("Unexpected retry loop termination")

    def _compute_backoff_delay(self, attempt: int, retry_after: str | None = None) -> float:
        if retry_after:
            try:
                parsed = float(retry_after)
                if parsed > 0:
                    return parsed
            except ValueError:
                pass

        exponential = self.retry_base_delay * (2 ** (attempt - 1))
        jitter = random.uniform(0, self.retry_base_delay)
        return exponential + jitter

    @staticmethod
    def _append_comments(body: str, top_comments: list[str]) -> str:
        if not top_comments:
            return body
        comment_lines = "\n".join(f"- {comment}" for comment in top_comments)
        if body.strip():
            return f"{body}\n\nTop comments:\n{comment_lines}"
        return f"Top comments:\n{comment_lines}"

