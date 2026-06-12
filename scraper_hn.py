import logging
import json
import math
from json import JSONDecodeError
from datetime import UTC, datetime, timedelta

import httpx

from scraper import Post

logger = logging.getLogger(__name__)
MAX_HN_RESPONSE_BYTES = 2_000_000


def _clean_text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    return str(value).strip()


def _parse_source_timestamp(hit: dict[str, object]) -> tuple[str | None, int | None]:
    raw_ts = hit.get("created_at_i")
    ts = 0
    if isinstance(raw_ts, str | int | float) and not isinstance(raw_ts, bool):
        try:
            numeric_ts = float(raw_ts)
            if math.isfinite(numeric_ts):
                ts = int(numeric_ts)
        except (TypeError, ValueError, OverflowError):
            ts = 0
    if ts > 0:
        try:
            dt = datetime.fromtimestamp(ts, tz=UTC)
        except (OverflowError, OSError, ValueError):
            return None, None
        return dt.isoformat(), ts

    raw_created_at = _clean_text(hit.get("created_at"))
    if not raw_created_at:
        return None, None
    try:
        dt = datetime.fromisoformat(raw_created_at.replace("Z", "+00:00"))
    except ValueError:
        return None, None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    else:
        dt = dt.astimezone(UTC)
    try:
        ts = int(dt.timestamp())
    except (OverflowError, OSError, ValueError):
        return None, None
    return dt.isoformat(), ts


def _merge_duplicate_post(existing: Post, incoming: Post) -> None:
    if existing.source_created_ts is None and incoming.source_created_ts is not None:
        existing.source_created_ts = incoming.source_created_ts
        existing.source_created_at = incoming.source_created_at
    elif existing.source_created_at is None and incoming.source_created_at is not None:
        existing.source_created_at = incoming.source_created_at
    if not existing.body and incoming.body:
        existing.body = incoming.body
    if existing.score == 0 and incoming.score:
        existing.score = incoming.score


class HackerNewsScraper:
    BASE_URL = "https://hn.algolia.com/api/v1/search_by_date"

    def __init__(self, user_agent: str = "pain_finder/1.0", max_response_bytes: int = MAX_HN_RESPONSE_BYTES):
        self.user_agent = user_agent
        self.max_response_bytes = max(1, max_response_bytes)

    async def _request_json_with_response_limit(
        self,
        client: httpx.AsyncClient,
        *,
        params: dict[str, object],
        headers: dict[str, str],
    ) -> object:
        async with client.stream("GET", self.BASE_URL, params=params, headers=headers) as response:
            response.raise_for_status()
            body = bytearray()
            async for chunk in response.aiter_bytes():
                body.extend(chunk)
                if len(body) > self.max_response_bytes:
                    raise ValueError(f"HN response exceeded {self.max_response_bytes} bytes")
            return json.loads(bytes(body).decode(response.encoding or "utf-8", errors="replace"))

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
                    payload = await self._request_json_with_response_limit(client, params=params, headers=headers)
                    if not isinstance(payload, dict):
                        raise ValueError("HN response must be a JSON object")
                except (httpx.HTTPError, JSONDecodeError, ValueError) as e:
                    logger.warning("HN fetch failed for query '%s': %s", keyword, e)
                    failed_queries.append(keyword)
                    continue

                successful_queries += 1
                for hit in payload.get("hits", []):
                    if not isinstance(hit, dict):
                        continue
                    object_id = str(hit.get("objectID", "")).strip()
                    if not object_id:
                        continue
                    post_id = f"hn:{object_id}"
                    title = _clean_text(hit.get("title") or hit.get("story_title"))
                    body = _clean_text(hit.get("story_text") or hit.get("comment_text"))
                    if not title and not body:
                        continue
                    url = _clean_text(hit.get("url") or hit.get("story_url")) or f"https://news.ycombinator.com/item?id={object_id}"
                    try:
                        score = int(hit.get("points") or 0)
                    except (TypeError, ValueError, OverflowError):
                        score = 0
                    source_created_at, source_created_ts = _parse_source_timestamp(hit)

                    post = Post(
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
                    existing = hits.get(post_id)
                    if existing is not None:
                        _merge_duplicate_post(existing, post)
                    else:
                        hits[post_id] = post
                    if len(hits) >= max_posts:
                        break
                if len(hits) >= max_posts:
                    break

        if attempted_queries and failed_queries and successful_queries == 0:
            raise RuntimeError(f"HN fetch failed for all {attempted_queries} keyword queries")

        return list(hits.values())[:max_posts]
