import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any

from openrouter import AnalysisResult, OpenRouterClient
from scraper import Post

logger = logging.getLogger(__name__)

COMPLAINT_WORDS = [
    "can't",
    "cannot",
    "broken",
    "frustrated",
    "frustrating",
    "annoying",
    "hate",
    "terrible",
    "awful",
    "useless",
    "fail",
    "failing",
    "doesn't work",
    "won't work",
    "keeps crashing",
    "impossible",
    "so bad",
    "worst",
]

UNSOLVED_WORDS = [
    "how do i",
    "how can i",
    "help me",
    "stuck on",
    "can't figure",
    "anyone know",
    "is there a way",
    "not sure how",
    "struggling with",
]

WISH_WORDS = [
    "wish",
    "would be nice",
    "feature request",
    "please add",
    "why doesn't",
    "why can't",
    "should have",
    "needs to have",
    "lacks",
    "missing",
]

B2C_REJECTION_WORDS = {
    "game",
    "gaming",
    "xbox",
    "playstation",
    "steam",
    "fortnite",
    "netflix",
    "movie",
    "tv show",
    "boyfriend",
    "girlfriend",
    "roommate",
}

BUSINESS_CONTEXT_WORDS = {
    "shopify",
    "agency",
    "client",
    "saas",
    "invoice",
    "crm",
    "workflow",
    "automation",
    "support team",
    "ecommerce",
    "b2b",
    "operations",
    "vendor",
    "customer",
    "subscription",
    "marketing",
}

COMPETITOR_HINTS = {
    "jira",
    "shopify",
    "salesforce",
    "quickbooks",
    "hubspot",
    "zendesk",
    "notion",
    "airtable",
    "slack",
    "asana",
    "monday",
}


@dataclass
class PainSignal:
    post: Post
    category: str
    summary: str
    severity: str
    is_monetizable: bool = False
    pain_level: int = 0
    willingness_to_pay: int = 0
    niche_category: str = ""
    competitor_tags: list[str] = field(default_factory=list)
    analysis_mode: str = "legacy"
    analysis_payload: dict[str, Any] | None = None


class Classifier:
    VALID_MODES = {"legacy", "b2b", "dual"}

    def __init__(self, openrouter: OpenRouterClient | None, mode: str = "dual"):
        self.openrouter = openrouter
        normalized_mode = mode.lower().strip()
        self.mode = normalized_mode if normalized_mode in self.VALID_MODES else "dual"

    def keyword_score(self, post: Post) -> int:
        text = f"{post.title} {post.body}".lower()
        score = 0
        if any(word in text for word in COMPLAINT_WORDS):
            score += 2
        if any(word in text for word in UNSOLVED_WORDS):
            score += 1
        if any(word in text for word in WISH_WORDS):
            score += 1
        return min(score, 3)

    def _keyword_category(self, post: Post) -> str:
        text = f"{post.title} {post.body}".lower()
        if any(word in text for word in COMPLAINT_WORDS):
            return "complaint"
        if any(word in text for word in UNSOLVED_WORDS):
            return "unsolved"
        return "wish"

    def _is_likely_b2c_noise(self, post: Post) -> bool:
        text = f"{post.title} {post.body}".lower()
        has_b2c = any(keyword in text for keyword in B2C_REJECTION_WORDS)
        has_business_context = any(keyword in text for keyword in BUSINESS_CONTEXT_WORDS)
        return has_b2c and not has_business_context

    @staticmethod
    def _normalize_competitor_tags(tags: list[str] | None) -> list[str]:
        if not tags:
            return []
        output = []
        seen = set()
        for tag in tags:
            if not isinstance(tag, str):
                continue
            clean = tag.strip().lower()
            if not clean:
                continue
            if len(clean) > 64:
                clean = clean[:64]
            if clean in seen:
                continue
            seen.add(clean)
            output.append(clean)
        return output

    def _extract_competitor_hints(self, post: Post) -> list[str]:
        text = f"{post.title} {post.body}".lower()
        return sorted([tag for tag in COMPETITOR_HINTS if tag in text])

    def _signal_from_analysis(self, post: Post, result: AnalysisResult, mode: str) -> PainSignal:
        pain_level = max(0, min(10, int(result.pain_level)))
        willingness_to_pay = max(0, min(10, int(result.willingness_to_pay)))
        return PainSignal(
            post=post,
            category=result.category,
            summary=result.summary,
            severity=result.severity,
            is_monetizable=bool(result.is_monetizable),
            pain_level=pain_level,
            willingness_to_pay=willingness_to_pay,
            niche_category=result.niche_category,
            competitor_tags=self._normalize_competitor_tags(result.competitor_tags),
            analysis_mode=mode,
            analysis_payload=result.raw_payload,
        )

    async def classify(self, post: Post) -> PainSignal | None:
        score = self.keyword_score(post)
        if score == 0:
            return None

        b2c_noise = self._is_likely_b2c_noise(post)

        if self.mode in {"b2b", "dual"} and self.openrouter:
            primary = await self.openrouter.analyze_post(title=post.title, body=post.body, post_id=post.post_id)
            if primary:
                signal = self._signal_from_analysis(post, primary, mode="b2b")
                if b2c_noise:
                    signal.is_monetizable = False
                    signal.willingness_to_pay = 0
                    signal.pain_level = min(signal.pain_level, 3)
                    signal.niche_category = signal.niche_category or "B2C-noise"
                if not signal.competitor_tags:
                    signal.competitor_tags = self._extract_competitor_hints(post)
                return signal
            if self.mode == "b2b":
                return None

        if self.mode in {"legacy", "dual"} and self.openrouter:
            legacy = await self.openrouter.analyze_legacy_post(title=post.title, body=post.body, post_id=post.post_id)
            if legacy:
                signal = self._signal_from_analysis(post, legacy, mode="legacy_llm")
                if b2c_noise:
                    signal.is_monetizable = False
                    signal.willingness_to_pay = 0
                    signal.pain_level = 0
                    signal.niche_category = "B2C-noise"
                else:
                    signal.is_monetizable = score >= 2
                    signal.pain_level = min(10, 4 + score * 2)
                    signal.willingness_to_pay = min(10, 3 + score * 2)
                    signal.niche_category = signal.niche_category or "Uncategorized"
                if not signal.competitor_tags:
                    signal.competitor_tags = self._extract_competitor_hints(post)
                return signal

        if self.mode == "b2b":
            return None

        category = self._keyword_category(post)
        return PainSignal(
            post=post,
            category=category,
            summary=post.title[:120],
            severity="medium" if score >= 2 else "low",
            is_monetizable=not b2c_noise and score >= 2,
            pain_level=0 if b2c_noise else min(10, 4 + score * 2),
            willingness_to_pay=0 if b2c_noise else min(10, 3 + score * 2),
            niche_category="B2C-noise" if b2c_noise else "Uncategorized",
            competitor_tags=self._extract_competitor_hints(post),
            analysis_mode="legacy",
        )

    async def classify_batch(self, posts: list[Post]) -> list[PainSignal]:
        signals = await asyncio.gather(*(self.classify(post) for post in posts))
        return [s for s in signals if s is not None]
