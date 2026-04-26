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

BUYER_AUTHORITY_SCORES = {
    "intern": 0.35,
    "ic": 0.6,
    "engineer": 0.72,
    "manager": 0.82,
    "head_of_ops": 0.94,
    "founder_owner": 1.0,
    "agency_operator": 0.88,
    "unknown": 0.55,
}
FIRST_HANDNESS_SCORES = {
    "first_hand": 1.0,
    "second_hand": 0.78,
    "aggregated": 0.7,
    "speculative": 0.45,
    "unknown": 0.58,
}
CONSENSUS_PATTERNS = (
    "same here",
    "same issue",
    "same problem",
    "me too",
    "we have this too",
    "here too",
    "also happens",
    "also happening",
    "we hit this too",
)
WORKAROUND_PATTERNS = (
    "manual workaround",
    "workaround",
    "export csv",
    "export to csv",
    "spreadsheet",
    "sheets",
    "copy paste",
    "copy/paste",
    "re-upload",
    "reupload",
    "script around",
    "zapier",
    "glue code",
)
SHILL_PATTERNS = (
    "try our tool",
    "book a demo",
    "sign up",
    "dm me",
    "reach out",
    "check out my",
    "we can help",
    "our product",
)
HIGH_IMPACT_PATTERNS = (
    "lose sales",
    "lost sales",
    "lost revenue",
    "revenue",
    "churn",
    "customers complain",
    "customer escalations",
    "compliance",
    "security risk",
    "refund",
)
MEDIUM_IMPACT_PATTERNS = (
    "hours",
    "days",
    "manual",
    "spreadsheet",
    "reconcile",
    "delay",
    "backlog",
    "broken",
    "failing",
    "crash",
    "error",
)
SOLVED_PATTERNS = (
    "fixed it",
    "solved",
    "resolved",
    "works now",
    "ended up using",
    "switched to",
    "temporary workaround",
)
HIGH_FREQUENCY_PATTERNS = (
    "every day",
    "daily",
    "every week",
    "weekly",
    "all the time",
    "each time",
    "every time",
    "constantly",
)


def buyer_authority_score(authority: str | None) -> float:
    return float(BUYER_AUTHORITY_SCORES.get((authority or "unknown").strip().lower(), BUYER_AUTHORITY_SCORES["unknown"]))


def first_handness_score(level: str | None) -> float:
    return float(FIRST_HANDNESS_SCORES.get((level or "unknown").strip().lower(), FIRST_HANDNESS_SCORES["unknown"]))


def extract_comment_market_signals(post: Post, competitor_tags: list[str] | None = None) -> dict[str, Any]:
    comments = [comment.strip() for comment in (post.top_comments or []) if isinstance(comment, str) and comment.strip()]
    same_here_count = 0
    consensus_count = 0
    workaround_count = 0
    shill_hits = 0
    tool_mentions: set[str] = {tag.strip().lower() for tag in (competitor_tags or []) if isinstance(tag, str) and tag.strip()}

    for comment in comments:
        lowered = comment.lower()
        same_here = any(
            pattern in lowered
            for pattern in {"same here", "same issue", "same problem", "me too", "we have this too", "we hit this too"}
        )
        workaround = any(pattern in lowered for pattern in WORKAROUND_PATTERNS)
        shill = any(pattern in lowered for pattern in SHILL_PATTERNS) or ("http://" in lowered or "https://" in lowered)
        if same_here:
            same_here_count += 1
            consensus_count += 1
        elif any(token in lowered for token in {"we hit this", "also", "us too", "same pain", "here too"}):
            consensus_count += 1
        if workaround:
            workaround_count += 1
        if shill:
            shill_hits += 1
        for tag in COMPETITOR_HINTS:
            if tag in lowered:
                tool_mentions.add(tag)

    shill_risk = round(min(1.0, shill_hits / max(1, len(comments))), 3) if comments else 0.0
    return {
        "comment_consensus_count": consensus_count,
        "comment_same_here_count": same_here_count,
        "comment_workaround_count": workaround_count,
        "comment_tool_mentions": sorted(tool_mentions),
        "comment_shill_risk": shill_risk,
        "comment_sample": comments[:5],
    }


def estimate_workflow_frequency_score(post: Post, signal: "PainSignal") -> float:
    text = "\n".join(part for part in [post.title, post.body, *post.top_comments] if part).lower()
    score = 0.32
    if any(pattern in text for pattern in HIGH_FREQUENCY_PATTERNS):
        score += 0.33
    if any(pattern in text for pattern in WORKAROUND_PATTERNS) or any(token in text for token in {"manual", "spreadsheet", "export", "reconcile"}):
        score += 0.2
    if signal.post_type in {"first_person_pain", "solution_request", "vendor_rant"}:
        score += 0.1
    return round(min(1.0, score), 3)


def estimate_impact_score(post: Post, signal: "PainSignal") -> float:
    text = "\n".join(part for part in [post.title, post.body, *post.top_comments] if part).lower()
    score = 0.2 + min(0.45, max(signal.pain_level, signal.willingness_to_pay) / 10 * 0.45)
    if any(pattern in text for pattern in HIGH_IMPACT_PATTERNS):
        score += 0.25
    if any(pattern in text for pattern in MEDIUM_IMPACT_PATTERNS):
        score += 0.12
    return round(min(1.0, score), 3)


def estimate_solved_penalty(post: Post, *, comment_signals: dict[str, Any]) -> float:
    text = "\n".join(part for part in [post.title, post.body, *post.top_comments] if part).lower()
    solved_hits = sum(1 for pattern in SOLVED_PATTERNS if pattern in text)
    if solved_hits == 0:
        return 0.0
    penalty = min(0.65, 0.18 * solved_hits + float(comment_signals.get("comment_workaround_count", 0)) * 0.04)
    return round(penalty, 3)


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
    buyer_authority_score: float = 0.55
    workflow_frequency_score: float = 0.0
    impact_score: float = 0.0
    consensus_score: float = 0.0
    incumbent_failure_score: float = 0.0
    recency_score: float = 0.0
    stale_penalty: float = 0.0
    solved_penalty: float = 0.0
    opportunity_score: float = 0.0
    comment_consensus_count: int = 0
    comment_same_here_count: int = 0
    comment_workaround_count: int = 0
    comment_tool_mentions: list[str] = field(default_factory=list)
    comment_shill_risk: float = 0.0
    comment_sample: list[str] = field(default_factory=list)
    score_components: dict[str, Any] | None = None


class Classifier:
    VALID_MODES = {"legacy", "b2b", "dual"}

    def __init__(
        self,
        openrouter: OpenRouterClient | None,
        dspy_parser: Any | None = None,
        mode: str = "dual",
        max_concurrency: int = 8,
        screen_min_rule_score: int = 1,
        screen_max_llm_candidates_per_run: int = 0,
    ):
        self.openrouter = openrouter
        self.dspy_parser = dspy_parser
        normalized_mode = mode.lower().strip()
        self.mode = normalized_mode if normalized_mode in self.VALID_MODES else "dual"
        self.max_concurrency = max(1, max_concurrency)
        self.screen_min_rule_score = max(0, int(screen_min_rule_score))
        self.screen_max_llm_candidates_per_run = max(0, int(screen_max_llm_candidates_per_run))

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

    def prescreen_score(self, post: Post) -> int:
        text = f"{post.title} {post.body}".lower()
        score = self.keyword_score(post)
        if any(token in text for token in BUSINESS_CONTEXT_WORDS):
            score += 1
        if any(token in text for token in {"manual", "process", "workflow", "spreadsheet", "csv", "approval", "handoff", "sync", "pain"}):
            score += 1
        if any(pattern in text for pattern in HIGH_FREQUENCY_PATTERNS):
            score += 1
        if self._extract_competitor_hints(post):
            score += 1
        if any(comment.strip() for comment in post.top_comments):
            score += 1
        if self._infer_first_handness(post, post_type=self._infer_post_type(post, category=self._keyword_category(post))) == "first_hand":
            score += 1
        if self._is_likely_b2c_noise(post):
            score = max(0, score - 1)
        return max(0, min(score, 7))

    def prescreen_posts(
        self,
        posts: list[Post],
        *,
        max_candidates: int | None = None,
    ) -> tuple[list[Post], dict[str, int]]:
        scored: list[tuple[int, Post]] = []
        rule_dropped_count = 0
        for post in posts:
            score = self.prescreen_score(post)
            if score < self.screen_min_rule_score:
                rule_dropped_count += 1
                continue
            scored.append((score, post))

        scored.sort(key=lambda item: item[0], reverse=True)
        kept_count = len(scored)
        capped_count = 0
        shortlisted = [post for _, post in scored]
        candidate_cap = self.screen_max_llm_candidates_per_run if max_candidates is None else max(0, int(max_candidates))
        if candidate_cap > 0 and len(shortlisted) > candidate_cap:
            capped_count = len(shortlisted) - candidate_cap
            shortlisted = shortlisted[:candidate_cap]
        return shortlisted, {
            "screen_rule_dropped_count": rule_dropped_count,
            "screen_kept_count": kept_count,
            "screen_capped_count": capped_count,
        }

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
        keyword_score = self.keyword_score(post)
        rule_score = self.prescreen_score(post)
        if rule_score < self.screen_min_rule_score:
            return None

        heuristic_score = max(keyword_score, min(3, rule_score))
        b2c_noise = self._is_likely_b2c_noise(post)
        dspy_attempted = False
        primary_attempted = False

        if self.mode in {"b2b", "dual"}:
            if self.dspy_parser is not None:
                dspy_attempted = True
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
                primary_attempted = True
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
            if self.mode == "legacy":
                legacy_fallback_reason = "mode_legacy"
            elif dspy_attempted and primary_attempted:
                legacy_fallback_reason = "dspy_empty_primary_unavailable"
            elif dspy_attempted:
                legacy_fallback_reason = "dspy_empty"
            elif primary_attempted:
                legacy_fallback_reason = "primary_unavailable"
            else:
                legacy_fallback_reason = "dual_no_primary"
            legacy = await self.openrouter.analyze_legacy_post(
                title=post.title,
                body=post.body,
                post_id=post.post_id,
                fallback_reason=legacy_fallback_reason,
            )
            if legacy:
                signal = self._signal_from_analysis(post, legacy, mode="legacy_llm")
                if b2c_noise:
                    signal.is_monetizable = False
                    signal.willingness_to_pay = 0
                    signal.pain_level = 0
                    signal.niche_category = "B2C-noise"
                else:
                    signal.is_monetizable = heuristic_score >= 2
                    signal.pain_level = min(10, 4 + heuristic_score * 2)
                    signal.willingness_to_pay = min(10, 3 + heuristic_score * 2)
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
            severity="medium" if heuristic_score >= 2 else "low",
            is_monetizable=not b2c_noise and heuristic_score >= 2,
            pain_level=0 if b2c_noise else min(10, 4 + heuristic_score * 2),
            willingness_to_pay=0 if b2c_noise else min(10, 3 + heuristic_score * 2),
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
