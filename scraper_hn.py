import logging
from datetime import UTC, datetime, timedelta

import httpx

from scraper import Post

logger = logging.getLogger(__name__)


class HackerNewsScraper:
    BASE_URL = "https://hn.algolia.com/api/v1/search_by_date"

    def __init__(self, user_agent: str = "pain_finder/1.0"):
        self.user_agent = user_agent

    async def fetch_posts(
        self,
        *,
        keywords: list[str],
        lookback_hours: int = 72,
        max_posts: int = 100,
    ) -> list[Post]:
        if not keywords or max_posts <= 0:
            return []

        headers = {"User-Agent": self.user_agent}
        since_ts = int((datetime.now(UTC) - timedelta(hours=max(1, lookback_hours))).timestamp())
        hits: dict[str, Post] = {}
        attempted_queries = 0
        successful_queries = 0
        failed_queries: list[str] = []

        async with httpx.AsyncClient(timeout=20) as client:
            for keyword in keywords:
                if not isinstance(keyword, str) or not keyword.strip():
                    continue
                attempted_queries += 1
                params = {
                    "query": keyword.strip(),
                    "tags": "story",
                    "hitsPerPage": min(max_posts, 100),
                    "numericFilters": f"created_at_i>{since_ts}",
                }
                try:
                    response = await client.get(self.BASE_URL, params=params, headers=headers)
                    response.raise_for_status()
                except httpx.HTTPError as e:
                    logger.warning("HN fetch failed for query '%s': %s", keyword, e)
                    failed_queries.append(keyword)
                    continue

                successful_queries += 1
                payload = response.json()
                for hit in payload.get("hits", []):
                    object_id = str(hit.get("objectID", "")).strip()
                    if not object_id:
                        continue
                    post_id = f"hn:{object_id}"
                    title = (hit.get("title") or hit.get("story_title") or "").strip()
                    body = (hit.get("story_text") or hit.get("comment_text") or "").strip()
                    if not title and not body:
                        continue
                    url = (hit.get("url") or hit.get("story_url") or f"https://news.ycombinator.com/item?id={object_id}").strip()
                    score = int(hit.get("points") or 0)

                    hits[post_id] = Post(
                        post_id=post_id,
                        subreddit="hackernews",
                        title=title or f"HN {object_id}",
                        body=body,
                        url=url,
                        score=score,
                        permalink=f"https://news.ycombinator.com/item?id={object_id}",
                        top_comments=[],
                        source="hn",
                    )
                    if len(hits) >= max_posts:
                        break
                if len(hits) >= max_posts:
                    break

        if attempted_queries and failed_queries and successful_queries == 0:
            raise RuntimeError(f"HN fetch failed for all {attempted_queries} keyword queries")

        return list(hits.values())[:max_posts]
