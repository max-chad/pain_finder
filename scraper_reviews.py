import json
import logging
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import httpx
from bs4 import BeautifulSoup

from scraper import Post

logger = logging.getLogger(__name__)

RATING_RE = re.compile(r"([1-5](?:\.\d+)?)")


@dataclass
class ReviewTarget:
    site: str
    name: str
    url: str
    enabled: bool = True


class ReviewScraper:
    def __init__(self, user_agent: str = "pain_finder/1.0"):
        self.user_agent = user_agent

    async def fetch_negative_reviews(
        self,
        *,
        target: ReviewTarget,
        max_reviews: int = 30,
    ) -> list[Post]:
        if not target.enabled or max_reviews <= 0:
            return []

        html = await self._fetch_html(target.url)
        if not html:
            return []

        site = target.site.strip().lower()
        if site == "appstore":
            rows = self._parse_appstore_reviews(html)
        elif site == "g2":
            rows = self._parse_generic_review_cards(html)
        elif site == "capterra":
            rows = self._parse_generic_review_cards(html)
        else:
            rows = self._parse_generic_review_cards(html)

        posts: list[Post] = []
        slug = re.sub(r"[^a-z0-9]+", "-", target.name.lower()).strip("-") or "unknown"
        for index, row in enumerate(rows[:max_reviews], start=1):
            rating = float(row.get("rating", 0))
            text = (row.get("text") or "").strip()
            if not text:
                continue
            if rating <= 0 or rating > 2.0:
                continue
            post_id = f"review:{site}:{slug}:{index}"
            posts.append(
                Post(
                    post_id=post_id,
                    subreddit=f"reviews_{site}",
                    title=f"{target.name} {rating:.1f} star review",
                    body=text,
                    url=target.url,
                    score=max(0, int((2.5 - rating) * 10)),
                    top_comments=[],
                    source=f"review:{site}",
                    source_created_at=row.get("source_created_at"),
                    source_created_ts=row.get("source_created_ts"),
                )
            )
        return posts

    async def fetch_many_targets(
        self,
        *,
        targets: list[ReviewTarget],
        max_per_target: int,
    ) -> list[Post]:
        all_posts: list[Post] = []
        for target in targets:
            target_posts = await self.fetch_negative_reviews(target=target, max_reviews=max_per_target)
            all_posts.extend(target_posts)
        return all_posts

    async def _fetch_html(self, url: str) -> str:
        headers = {"User-Agent": self.user_agent}
        try:
            async with httpx.AsyncClient(timeout=25) as client:
                response = await client.get(url, headers=headers)
                response.raise_for_status()
                return response.text
        except httpx.HTTPError as e:
            logger.warning("Review scraper failed for %s: %s", url, e)
            return ""

    def _parse_appstore_reviews(self, html: str) -> list[dict[str, Any]]:
        soup = BeautifulSoup(html, "html.parser")
        rows: list[dict[str, Any]] = []

        for script in soup.find_all("script", {"type": "application/ld+json"}):
            raw = script.string or script.text or ""
            raw = raw.strip()
            if not raw:
                continue
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if isinstance(payload, list):
                nodes = payload
            else:
                nodes = [payload]
            for node in nodes:
                if not isinstance(node, dict):
                    continue
                if node.get("@type") != "Review":
                    continue
                review_rating = node.get("reviewRating", {})
                rating_value = float(review_rating.get("ratingValue") or 0)
                review_text = str(node.get("reviewBody") or "").strip()
                source_created_at, source_created_ts = self._source_created_fields(node.get("datePublished"))
                rows.append(
                    {
                        "rating": rating_value,
                        "text": review_text,
                        "source_created_at": source_created_at,
                        "source_created_ts": source_created_ts,
                    }
                )
        return rows

    def _parse_generic_review_cards(self, html: str) -> list[dict[str, Any]]:
        soup = BeautifulSoup(html, "html.parser")
        rows: list[dict[str, Any]] = []

        candidate_nodes = soup.select(
            "[data-review-id], .review, .review-card, article, [itemprop='review'], [class*='review']"
        )
        for node in candidate_nodes:
            text = " ".join(part.strip() for part in node.stripped_strings if part.strip())
            if not text:
                continue

            rating = self._extract_rating(node=node, text=text)
            if rating <= 0:
                continue
            source_created_at, source_created_ts = self._extract_source_created(node)
            rows.append(
                {
                    "rating": rating,
                    "text": text,
                    "source_created_at": source_created_at,
                    "source_created_ts": source_created_ts,
                }
            )

        return rows

    def _extract_source_created(self, node) -> tuple[str | None, int | None]:
        for candidate in [node, *node.find_all(["time", "meta"])]:
            for attr in ("datetime", "content", "datepublished", "data-date", "title"):
                value = candidate.get(attr)
                if isinstance(value, str) and value.strip():
                    parsed = self._source_created_fields(value)
                    if parsed != (None, None):
                        return parsed
        return None, None

    def _extract_rating(self, *, node, text: str) -> float:
        for attr in ("aria-label", "title", "data-rating", "data-stars"):
            attr_value = node.get(attr)
            if isinstance(attr_value, str):
                parsed = self._parse_rating_from_text(attr_value)
                if parsed > 0:
                    return parsed

        for child in node.find_all(attrs={"aria-label": True}):
            label = child.get("aria-label")
            if isinstance(label, str):
                parsed = self._parse_rating_from_text(label)
                if parsed > 0:
                    return parsed

        return self._parse_rating_from_text(text)

    @staticmethod
    def _parse_rating_from_text(text: str) -> float:
        lowered = text.lower()
        if "star" not in lowered and "rating" not in lowered:
            return 0.0
        match = RATING_RE.search(lowered)
        if not match:
            return 0.0
        try:
            value = float(match.group(1))
        except ValueError:
            return 0.0
        if value < 0 or value > 5:
            return 0.0
        return value

    @staticmethod
    def _source_created_fields(value: Any) -> tuple[str | None, int | None]:
        raw = str(value or "").strip()
        if not raw:
            return None, None
        if raw.isdigit():
            timestamp = int(raw)
            if timestamp >= 10_000_000_000:
                timestamp //= 1000
            try:
                return datetime.fromtimestamp(timestamp, UTC).isoformat(), timestamp
            except (OSError, OverflowError, ValueError):
                return None, None
        try:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            return None, None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        parsed = parsed.astimezone(UTC)
        try:
            return parsed.isoformat(), int(parsed.timestamp())
        except (OSError, OverflowError, ValueError):
            return None, None
