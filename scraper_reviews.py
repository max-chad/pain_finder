import json
import logging
import re
import hashlib
from dataclasses import dataclass
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


class ReviewFetchError(RuntimeError):
    pass


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
        for row in rows:
            if len(posts) >= max_reviews:
                break
            rating = float(row.get("rating", 0))
            text = (row.get("text") or "").strip()
            if not text:
                continue
            if rating <= 0 or rating > 2.0:
                continue
            post_id = self._review_post_id(site=site, slug=slug, url=target.url, rating=rating, text=text)
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
        attempted_targets = 0
        successful_targets = 0
        failed_targets: list[str] = []
        for target in targets:
            if not target.enabled or max_per_target <= 0:
                continue
            attempted_targets += 1
            try:
                target_posts = await self.fetch_negative_reviews(target=target, max_reviews=max_per_target)
            except ReviewFetchError as exc:
                failed_targets.append(target.name)
                logger.warning("Review target failed for %s: %s", target.name, exc)
                continue
            successful_targets += 1
            all_posts.extend(target_posts)
        if attempted_targets and failed_targets and successful_targets == 0:
            raise RuntimeError(f"Review fetch failed for all {attempted_targets} enabled targets")
        return all_posts

    @staticmethod
    def _review_post_id(*, site: str, slug: str, url: str, rating: float, text: str) -> str:
        normalized_text = " ".join(text.lower().split())
        identity = json.dumps(
            {
                "site": site,
                "slug": slug,
                "url": url.strip().lower(),
                "rating": round(rating, 2),
                "text": normalized_text,
            },
            sort_keys=True,
            ensure_ascii=True,
        )
        digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:16]
        return f"review:{site}:{slug}:{digest}"

    async def _fetch_html(self, url: str) -> str:
        headers = {"User-Agent": self.user_agent}
        try:
            async with httpx.AsyncClient(timeout=25) as client:
                response = await client.get(url, headers=headers)
                response.raise_for_status()
                return response.text
        except httpx.HTTPError as e:
            logger.warning("Review scraper failed for %s: %s", url, e)
            raise ReviewFetchError(f"Review scraper failed for {url}") from e

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
                rows.append({"rating": rating_value, "text": review_text})
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
            rows.append({"rating": rating, "text": text})

        return rows

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
