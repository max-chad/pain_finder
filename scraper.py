import asyncio
import logging
import random
from dataclasses import dataclass, field
from typing import Any

import httpx

logger = logging.getLogger(__name__)
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}


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


class RedditScraper:
    def __init__(
        self,
        client_id: str,
        client_secret: str,
        user_agent: str,
        top_comments_limit: int = 5,
        retry_max_attempts: int = 5,
        retry_base_delay: float = 1.0,
    ):
        self.client_id = client_id
        self.client_secret = client_secret
        self.user_agent = user_agent
        self.top_comments_limit = max(0, top_comments_limit)
        self.retry_max_attempts = max(1, retry_max_attempts)
        self.retry_base_delay = max(0.1, retry_base_delay)
        self._use_praw = bool(client_id and client_secret)

    async def fetch_posts(self, subreddit: str, limit: int = 100, timeframe: str = "day") -> list[Post]:
        if self._use_praw:
            try:
                return await self._fetch_praw(subreddit, limit, timeframe)
            except Exception as e:
                logger.warning("PRAW failed (%s), falling back to public JSON", e)
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
                logger.warning("PRAW full thread failed (%s), using JSON fallback", e)
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

    async def _fetch_praw(self, subreddit: str, limit: int, timeframe: str) -> list[Post]:
        import praw

        def _sync_fetch() -> list[Post]:
            reddit = praw.Reddit(
                client_id=self.client_id,
                client_secret=self.client_secret,
                user_agent=self.user_agent,
            )
            posts: list[Post] = []
            sub = reddit.subreddit(subreddit)
            for submission in sub.top(time_filter=timeframe, limit=limit):
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
                posts.append(
                    Post(
                        post_id=self._external_post_id(submission.id),
                        subreddit=subreddit,
                        title=submission.title,
                        body=body,
                        url=f"https://reddit.com{submission.permalink}",
                        score=submission.score,
                        permalink=submission.permalink,
                        top_comments=top_comments,
                    )
                )
            return posts

        return await asyncio.to_thread(_sync_fetch)

    async def _fetch_public_json(self, subreddit: str, limit: int, timeframe: str = "day") -> list[Post]:
        url = f"https://www.reddit.com/r/{subreddit}/top.json"
        params = {"limit": min(limit, 100), "t": timeframe, "raw_json": 1}
        headers = {"User-Agent": self.user_agent}

        async with httpx.AsyncClient() as client:
            payload = await self._request_json_with_retries(
                client=client,
                url=url,
                params=params,
                headers=headers,
            )

            base_posts: list[Post] = []
            for child in payload.get("data", {}).get("children", []):
                post_data = child.get("data", {})
                post_id = post_data.get("id")
                if not post_id:
                    continue
                prefixed_post_id = self._external_post_id(post_id)
                permalink = post_data.get("permalink", "")
                if permalink and not permalink.startswith("http"):
                    full_url = f"https://reddit.com{permalink}"
                else:
                    full_url = post_data.get("url", "")

                base_posts.append(
                    Post(
                        post_id=prefixed_post_id,
                        subreddit=subreddit,
                        title=post_data.get("title", ""),
                        body=post_data.get("selftext", ""),
                        url=full_url,
                        score=int(post_data.get("score", 0) or 0),
                        permalink=permalink,
                    )
                )

            if self.top_comments_limit <= 0 or not base_posts:
                return base_posts

            semaphore = asyncio.Semaphore(8)

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

