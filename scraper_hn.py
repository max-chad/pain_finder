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

        async with httpx.AsyncClient(timeout=20) as client:
            for keyword in keywords:
                if not isinstance(keyword, str) or not keyword.strip():
                    continue
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
                    continue

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
                    source_created_at, source_created_ts = self._source_created_fields(hit)

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
                        source_created_at=source_created_at,
                        source_created_ts=source_created_ts,
                    )
                    if len(hits) >= max_posts:
                        break
                if len(hits) >= max_posts:
                    break

        return list(hits.values())[:max_posts]

    @staticmethod
    def _source_created_fields(hit: dict) -> tuple[str | None, int | None]:
        source_created_ts: int | None = None
        raw_ts = hit.get("created_at_i")
        if raw_ts not in (None, ""):
            try:
                source_created_ts = int(raw_ts)
            except (TypeError, ValueError):
                source_created_ts = None

        raw_created_at = str(hit.get("created_at") or "").strip()
        if raw_created_at:
            normalized = raw_created_at.replace("Z", "+00:00")
            try:
                created_dt = datetime.fromisoformat(normalized)
            except ValueError:
                created_dt = None
            if created_dt is not None:
                if created_dt.tzinfo is None:
                    created_dt = created_dt.replace(tzinfo=UTC)
                created_dt = created_dt.astimezone(UTC)
                created_ts = int(created_dt.timestamp())
                return created_dt.isoformat(), created_ts

        if source_created_ts is not None:
            try:
                return datetime.fromtimestamp(source_created_ts, UTC).isoformat(), source_created_ts
            except (OSError, OverflowError, ValueError):
                return None, None
        return None, None
