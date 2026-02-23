import logging
import asyncio
from dataclasses import dataclass
import httpx

logger = logging.getLogger(__name__)
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}
RETRY_BACKOFF_SECONDS = (0.5, 1.0)


@dataclass
class Post:
    post_id: str
    subreddit: str
    title: str
    body: str
    url: str
    score: int


class RedditScraper:
    def __init__(self, client_id: str, client_secret: str, user_agent: str):
        self.client_id = client_id
        self.client_secret = client_secret
        self.user_agent = user_agent
        self._use_praw = bool(client_id and client_secret)

    async def fetch_posts(self, subreddit: str, limit: int = 100, timeframe: str = "day") -> list[Post]:
        if self._use_praw:
            try:
                return await self._fetch_praw(subreddit, limit, timeframe)
            except Exception as e:
                logger.warning("PRAW failed (%s), falling back to public JSON", e)
        return await self._fetch_public_json(subreddit, limit, timeframe)

    async def _fetch_praw(self, subreddit: str, limit: int, timeframe: str) -> list[Post]:
        import praw

        def _sync_fetch() -> list[Post]:
            reddit = praw.Reddit(
                client_id=self.client_id,
                client_secret=self.client_secret,
                user_agent=self.user_agent,
            )
            posts = []
            sub = reddit.subreddit(subreddit)
            for submission in sub.top(time_filter=timeframe, limit=limit):
                posts.append(Post(
                    post_id=submission.id,
                    subreddit=subreddit,
                    title=submission.title,
                    body=submission.selftext or "",
                    url=f"https://reddit.com{submission.permalink}",
                    score=submission.score,
                ))
            return posts

        return await asyncio.to_thread(_sync_fetch)

    async def _fetch_public_json(self, subreddit: str, limit: int, timeframe: str = "day") -> list[Post]:
        url = f"https://www.reddit.com/r/{subreddit}/top.json"
        params = {"limit": min(limit, 100), "t": timeframe}
        headers = {"User-Agent": self.user_agent}
        async with httpx.AsyncClient() as client:
            data = None
            for attempt in range(1, 3):
                try:
                    resp = await client.get(url, params=params, headers=headers, timeout=15)
                    resp.raise_for_status()
                    data = resp.json()
                    break
                except httpx.HTTPStatusError as e:
                    status_code = e.response.status_code if e.response else None
                    if status_code in RETRYABLE_STATUS_CODES and attempt < 2:
                        delay = RETRY_BACKOFF_SECONDS[attempt - 1]
                        logger.warning(
                            "Reddit public JSON transient HTTP %s (attempt %d/2), retrying in %.1fs",
                            status_code,
                            attempt,
                            delay,
                        )
                        await asyncio.sleep(delay)
                        continue
                    raise
                except httpx.RequestError as e:
                    if attempt < 2:
                        delay = RETRY_BACKOFF_SECONDS[attempt - 1]
                        logger.warning(
                            "Reddit public JSON request error %s (attempt %d/2), retrying in %.1fs",
                            e,
                            attempt,
                            delay,
                        )
                        await asyncio.sleep(delay)
                        continue
                    raise

            if data is None:
                raise RuntimeError("Reddit public JSON fetch failed without response data")
        posts = []
        for child in data.get("data", {}).get("children", []):
            d = child["data"]
            posts.append(Post(
                post_id=d["id"],
                subreddit=subreddit,
                title=d.get("title", ""),
                body=d.get("selftext", ""),
                url=d.get("url", ""),
                score=d.get("score", 0),
            ))
        return posts
