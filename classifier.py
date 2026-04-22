import asyncio
import logging
import re
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
    post_type: str = "advice_thread"
    first_handness: str = "unknown"
    buyer_authority: str = "unknown"
    evidence_spans: list[str] = field(default_factory=list)
    opportunity_bucket: str = "unknown_age"


class Classifier:
    VALID_MODES = {"legacy", "b2b", "dual"}

    def __init__(
        self,
        openrouter: OpenRouterClient | None,
        dspy_parser: Any | None = None,
        mode: str = "dual",
        max_concurrency: int = 8,
    ):
        self.openrouter = openrouter
        self.dspy_parser = dspy_parser
        normalized_mode = mode.lower().strip()
        self.mode = normalized_mode if normalized_mode in self.VALID_MODES else "dual"
        self.max_concurrency = max(1, max_concurrency)

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

    def _infer_post_type(self, post: Post, *, category: str) -> str:
        text = f"{post.title} {post.body}".lower()
        if any(marker in text for marker in {" vs ", "versus", "alternative to", "compare", "comparison"}):
            return "tool_comparison"
        if any(marker in text for marker in {"launching", "i built", "we built", "looking for cofounder", "serious only", "my saas"}):
            return "founder_pitch"
        if any(marker in text for marker in {"news recap", "industry news", "weekly recap", "analysis", "lawsuit"}):
            return "news_analysis"
        if category == "complaint" and self._extract_competitor_hints(post):
            return "vendor_rant"
        if category == "unsolved":
            return "solution_request"
        if category == "complaint":
            return "first_person_pain"
        return "advice_thread"

    def _infer_first_handness(self, post: Post, *, post_type: str) -> str:
        text = f" {post.title} {post.body} ".lower()
        if post_type == "news_analysis":
            return "speculative"
        if any(marker in text for marker in {"my clients", "our clients", "customer interviews", "i interviewed", "we interviewed"}):
            return "aggregated"
        if any(marker in text for marker in {"my customer", "our customer", "my team", "our team"}):
            return "second_hand"
        if any(marker in text for marker in {" i ", " i'm ", " i’ve ", " i've ", " my ", " we ", " we're ", " our "}):
            return "first_hand"
        if any(marker in text for marker in {"people say", "founders say", "users say", "everyone says"}):
            return "aggregated"
        return "unknown"

    def _infer_buyer_authority(self, post: Post) -> str:
        text = f"{post.title} {post.body}".lower()
        if any(marker in text for marker in {"founder", "cofounder", "business owner", "owner", "ceo"}):
            return "founder_owner"
        if any(marker in text for marker in {"head of ops", "head of operations", "director of ops", "vp operations", "ops lead"}):
            return "head_of_ops"
        if any(marker in text for marker in {"agency", "client work", "client projects", "freelance agency"}):
            return "agency_operator"
        if any(marker in text for marker in {"intern", "student", "graduate"}):
            return "intern"
        if any(marker in text for marker in {"manager", "team lead", "lead "}):
            return "manager"
        if any(marker in text for marker in {"engineer", "developer", "devops", "sysadmin", "sre"}):
            return "engineer"
        if any(marker in text for marker in {"analyst", "specialist", "coordinator", "individual contributor"}):
            return "ic"
        return "unknown"

    def _extract_evidence_spans(self, post: Post) -> list[str]:
        text = "\n".join(part for part in [post.title, post.body] if part).strip()
        if not text:
            return []
        parts = [segment.strip() for segment in re.split(r"[\n.!?]+", text) if segment.strip()]
        spans: list[str] = []
        keywords = tuple(COMPLAINT_WORDS + UNSOLVED_WORDS + WISH_WORDS)
        for segment in parts:
            lowered = segment.lower()
            if any(keyword in lowered for keyword in keywords) or any(
                token in lowered for token in {"manual", "hours", "days", "$", "spreadsheet", "workaround", "broken"}
            ):
                spans.append(segment[:160])
            if len(spans) >= 3:
                break
        if not spans:
            spans.append(post.title[:160])
        return spans[:3]

    def _signal_from_analysis(self, post: Post, result: AnalysisResult, mode: str) -> PainSignal:
        pain_level = max(0, min(10, int(result.pain_level)))
        willingness_to_pay = max(0, min(10, int(result.willingness_to_pay)))
        inferred_post_type = result.post_type or self._infer_post_type(post, category=result.category)
        evidence_spans = result.evidence_spans or self._extract_evidence_spans(post)
        first_handness = result.first_handness if result.first_handness != "unknown" else self._infer_first_handness(post, post_type=inferred_post_type)
        buyer_authority = result.buyer_authority if result.buyer_authority != "unknown" else self._infer_buyer_authority(post)
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
            post_type=inferred_post_type,
            first_handness=first_handness,
            buyer_authority=buyer_authority,
            evidence_spans=evidence_spans,
        )

    async def classify(self, post: Post) -> PainSignal | None:
        score = self.keyword_score(post)
        if score == 0:
            return None

        b2c_noise = self._is_likely_b2c_noise(post)

        if self.mode in {"b2b", "dual"}:
            if self.dspy_parser is not None:
                primary = await self.dspy_parser.analyze_post(post)
                if primary:
                    signal = self._signal_from_analysis(post, primary, mode="dspy_b2b")
                    if b2c_noise:
                        signal.is_monetizable = False
                        signal.willingness_to_pay = 0
                        signal.pain_level = min(signal.pain_level, 3)
                        signal.niche_category = signal.niche_category or "B2C-noise"
                    if not signal.competitor_tags:
                        signal.competitor_tags = self._extract_competitor_hints(post)
                    return signal
            if self.openrouter:
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
        inferred_post_type = self._infer_post_type(post, category=category)
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
            post_type=inferred_post_type,
            first_handness=self._infer_first_handness(post, post_type=inferred_post_type),
            buyer_authority=self._infer_buyer_authority(post),
            evidence_spans=self._extract_evidence_spans(post),
        )

    async def classify_batch(self, posts: list[Post]) -> list[PainSignal]:
        semaphore = asyncio.Semaphore(self.max_concurrency)

        async def _classify_with_limit(post: Post) -> PainSignal | None:
            async with semaphore:
                return await self.classify(post)

        signals = await asyncio.gather(*(_classify_with_limit(post) for post in posts))
        return [s for s in signals if s is not None]
