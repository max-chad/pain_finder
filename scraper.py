import asyncio
import logging
import math
import random
import time
from dataclasses import dataclass, field
from typing import Any

import httpx

logger = logging.getLogger(__name__)
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}
ALLOWED_FEEDS = {"top", "new", "rising"}
DEFAULT_FEEDS = ("top",)


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
    ):
        self.client_id = client_id
        self.client_secret = client_secret
        self.user_agent = user_agent
        self.top_comments_limit = max(0, top_comments_limit)
        self.comment_fetch_concurrency = max(1, comment_fetch_concurrency)
        self.retry_max_attempts = max(1, retry_max_attempts)
        self.retry_base_delay = max(0.1, retry_base_delay)
        self._use_praw = bool(client_id and client_secret)
        self.feed_mix = self._normalize_feeds(feed_mix)
        self.search_queries = self._normalize_search_queries(search_queries)
        self._oauth_access_token: str = ""
        self._oauth_token_expires_at = 0.0

    async def fetch_posts(self, subreddit: str, limit: int = 100, timeframe: str = "day") -> list[Post]:
        if self._use_praw:
            try:
                return await self._fetch_praw(subreddit, limit, timeframe)
            except Exception as e:
                logger.warning("PRAW failed (%s), falling back to OAuth JSON", e)
            try:
                return await self._fetch_oauth_json(subreddit, limit, timeframe)
            except Exception as e:
                logger.warning("OAuth JSON failed (%s), falling back to public JSON", e)
        return await self._fetch_public_json(subreddit, limit, timeframe)

    async def fetch_full_thread(
        self,
        subreddit: str,
        post_id: str,
        max_comments: int = 250,
    ) -> list[str]:
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
        return Post(
            post_id=prefixed_post_id,
            subreddit=subreddit,
            title=post_data.get("title", ""),
            body=post_data.get("selftext", ""),
            url=full_url,
            score=int(post_data.get("score", 0) or 0),
            permalink=permalink,
            discovery_query=discovery_query,
        )

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
                    post = Post(
                        post_id=self._external_post_id(submission.id),
                        subreddit=subreddit,
                        title=submission.title,
                        body=body,
                        url=f"https://reddit.com{submission.permalink}",
                        score=submission.score,
                        permalink=submission.permalink,
                        top_comments=top_comments,
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
                    post = Post(
                        post_id=self._external_post_id(submission.id),
                        subreddit=subreddit,
                        title=submission.title,
                        body=submission.selftext or "",
                        url=f"https://reddit.com{submission.permalink}",
                        score=submission.score,
                        permalink=submission.permalink,
                        discovery_query=query,
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

            async def fetch_feed(feed: str, params: dict[str, Any]) -> Any:
                url = f"https://www.reddit.com/r/{subreddit}/{feed}.json"
                return await self._request_json_with_retries(
                    client=client,
                    url=url,
                    params=params,
                    headers=headers,
                )

            payloads = await asyncio.gather(*(fetch_feed(feed, params) for feed, params in feed_requests))

            for payload in payloads:
                for child in payload.get("data", {}).get("children", []):
                    post = self._build_post(subreddit, child.get("data", {}))
                    if post is None:
                        continue
                    self._merge_post(posts_by_id, post)

            async def fetch_search(query: str, params: dict[str, Any]) -> Any:
                url = f"https://www.reddit.com/r/{subreddit}/search.json"
                return await self._request_json_with_retries(
                    client=client,
                    url=url,
                    params=params,
                    headers=headers,
                )

            search_payloads = await asyncio.gather(
                *(fetch_search(query, params) for query, params in self._iter_search_requests(limit=limit))
            )
            for (query, _), payload in zip(self._iter_search_requests(limit=limit), search_payloads, strict=False):
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

    async def _fetch_oauth_json(self, subreddit: str, limit: int, timeframe: str = "day") -> list[Post]:
        async with httpx.AsyncClient() as client:
            posts_by_id: dict[str, Post] = {}
            feed_requests = self._iter_feed_requests(limit=limit, timeframe=timeframe)

            async def fetch_feed(feed: str, params: dict[str, Any]) -> Any:
                return await self._request_oauth_json(
                    client=client,
                    path=f"/r/{subreddit}/{feed}.json",
                    params=params,
                )

            payloads = await asyncio.gather(*(fetch_feed(feed, params) for feed, params in feed_requests))

            for payload in payloads:
                for child in payload.get("data", {}).get("children", []):
                    post = self._build_post(subreddit, child.get("data", {}))
                    if post is None:
                        continue
                    self._merge_post(posts_by_id, post)

            async def fetch_search(query: str, params: dict[str, Any]) -> Any:
                return await self._request_oauth_json(
                    client=client,
                    path=f"/r/{subreddit}/search.json",
                    params=params,
                )

            search_payloads = await asyncio.gather(
                *(fetch_search(query, params) for query, params in self._iter_search_requests(limit=limit))
            )
            for (query, _), payload in zip(self._iter_search_requests(limit=limit), search_payloads, strict=False):
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

        response = await client.post(
            "https://www.reddit.com/api/v1/access_token",
            data={"grant_type": "client_credentials"},
            auth=(self.client_id, self.client_secret),
            headers={"User-Agent": self.user_agent},
            timeout=20,
        )
        response.raise_for_status()
        payload = response.json()
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

        if not isinstance(payload, list) or len(payload) < 2:
            return []

        comments_listing = payload[1].get("data", {}).get("children", [])
        comments: list[str] = []
        for child in comments_listing:
            if child.get("kind") != "t1":
                continue
            body = child.get("data", {}).get("body", "")
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
            return []

        if not isinstance(payload, list) or len(payload) < 2:
            return []

        comments_listing = payload[1].get("data", {}).get("children", [])
        comments: list[str] = []
        for child in comments_listing:
            if child.get("kind") != "t1":
                continue
            body = child.get("data", {}).get("body", "")
            if isinstance(body, str) and body.strip():
                comments.append(body.strip())
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

        if not isinstance(payload, list) or len(payload) < 2:
            return []

        comment_nodes = payload[1].get("data", {}).get("children", [])
        comments: list[str] = []

        def walk(nodes: list[dict[str, Any]]) -> None:
            for node in nodes:
                if len(comments) >= max_comments:
                    return
                if node.get("kind") != "t1":
                    continue
                data = node.get("data", {})
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
            payload = await self._request_json_with_retries(
                client=client,
                url=url,
                params=params,
                headers=headers,
            )

        if not isinstance(payload, list) or len(payload) < 2:
            return []

        comment_nodes = payload[1].get("data", {}).get("children", [])
        comments: list[str] = []

        def walk(nodes: list[dict[str, Any]]) -> None:
            for node in nodes:
                if len(comments) >= max_comments:
                    return
                if node.get("kind") != "t1":
                    continue
                data = node.get("data", {})
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
                response = await client.get(url, params=params, headers=headers, timeout=20)
                response.raise_for_status()
                return response.json()
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

