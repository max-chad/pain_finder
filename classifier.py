import asyncio
import logging
import re
from dataclasses import dataclass, field
from typing import Any

from evidence import EvidenceSource, VerifiedEvidence, verify_evidence_spans
from embedder import cosine_similarity
from openrouter import AnalysisResult, OpenRouterClient, PainDetectionResult
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
OPERATIONAL_CONSEQUENCE_PATTERNS = (
    "reconcile",
    "reconciliation",
    "sync",
    "integration",
    "export",
    "csv",
    "handoff",
    "approval",
    "deadline",
    "sla",
    "manual work",
    "manual process",
    "workaround",
    "switching",
    "migration",
    "pricing lock",
    "lock-in",
    "lock in",
    "payout",
    "payroll",
    "invoice",
    "duplicate entry",
    "copy paste",
    "copy/paste",
    "spreadsheet",
    "quickbooks",
    "shopify",
)
HIDDEN_PAIN_QUESTION_PATTERNS = (
    "does anyone have",
    "anyone have",
    "sane way",
    "better way",
    "how are you handling",
    "how do you handle",
    "what do you use",
    "any tool",
    "tool for",
    "alternative to",
    "recommend",
)
SEMANTIC_CANDIDATE_QUERIES = (
    "manual workflow workaround causes repeated operational overhead",
    "reconcile payments invoices payouts between business systems",
    "tool sync integration failure export csv spreadsheet handoff",
    "switching from incumbent software because pricing support reliability is painful",
    "deadline approval customer escalation caused by broken internal process",
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
    pain_type: str = "unknown"
    expression_type: str = "unknown"
    user_context: str = ""
    user_context_json: dict[str, Any] = field(default_factory=dict)
    intensity: int = 0
    intensity_score: float = 0.0
    frequency: int = 0
    frequency_signal: str = "single"
    urgency: int | str = 0
    current_workaround: str = ""
    wtp_score: float = 0.0
    incumbent_failure: str = ""
    evidence_spans: list[str] = field(default_factory=list)
    opportunity_type: str = "unknown"
    verified_evidence: list[VerifiedEvidence] = field(default_factory=list)
    evidence_quality: str = "no_quote"
    evidence_match_rate: float = 0.0
    confidence: float = 0.0
    uncertainty_reason: str = ""
    needs_human_review: bool = False
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
    promotion_eligible: bool = False
    evidence_rejection_reason: str = ""
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
        semantic_candidate_queries: list[str] | None = None,
        staged_pain_detection_enabled: bool = False,
    ):
        self.openrouter = openrouter
        self.dspy_parser = dspy_parser
        normalized_mode = mode.lower().strip()
        self.mode = normalized_mode if normalized_mode in self.VALID_MODES else "dual"
        self.max_concurrency = max(1, max_concurrency)
        self.screen_min_rule_score = max(0, int(screen_min_rule_score))
        self.screen_max_llm_candidates_per_run = max(0, int(screen_max_llm_candidates_per_run))
        self.staged_pain_detection_enabled = bool(staged_pain_detection_enabled)
        self.semantic_candidate_queries = [
            str(query).strip()
            for query in (semantic_candidate_queries or list(SEMANTIC_CANDIDATE_QUERIES))
            if isinstance(query, str) and query.strip()
        ]
        self._semantic_rescue_post_ids: set[str] = set()

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

    @staticmethod
    def candidate_text(post: Post) -> str:
        return "\n".join(
            part
            for part in [post.title, post.body, *(post.top_comments or [])]
            if isinstance(part, str) and part.strip()
        ).lower()

    def operational_consequence_score(self, post: Post) -> int:
        """High-recall deterministic score for implicit operational pain.

        This catches posts that ask for a sane/better way to do work across
        tools without saying "hate", "broken", or "problem" explicitly.
        """
        text = self.candidate_text(post)
        consequence_hits = sum(1 for pattern in OPERATIONAL_CONSEQUENCE_PATTERNS if pattern in text)
        if consequence_hits <= 0:
            return 0

        score = min(2, consequence_hits)
        if any(pattern in text for pattern in HIDDEN_PAIN_QUESTION_PATTERNS):
            score += 1
        competitor_hits = self._extract_competitor_hints(post)
        if len(competitor_hits) >= 2 and any(pattern in text for pattern in {"sync", "reconcile", "integration", "export", "payout"}):
            score += 1
        if any(pattern in text for pattern in {"deadline", "sla", "blocked", "blocking", "customer escalation", "customers complain"}):
            score += 1
        return min(score, 5)

    def prescreen_score(self, post: Post) -> int:
        text = self.candidate_text(post)
        score = self.keyword_score(post)
        operational_score = self.operational_consequence_score(post)
        score += operational_score
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
        return max(0, min(score, 10))

    def prescreen_posts(
        self,
        posts: list[Post],
        *,
        max_candidates: int | None = None,
    ) -> tuple[list[Post], dict[str, Any]]:
        scored: list[tuple[int, int, int, Post]] = []
        rule_dropped_count = 0
        high_recall_candidate_count = 0
        for index, post in enumerate(posts):
            score = self.prescreen_score(post)
            operational_score = self.operational_consequence_score(post)
            if operational_score > 0:
                high_recall_candidate_count += 1
            if score < self.screen_min_rule_score:
                rule_dropped_count += 1
                continue
            scored.append((score, operational_score, -index, post))

        scored.sort(key=lambda item: (item[0], item[1], item[2]), reverse=True)
        kept_count = len(scored)
        capped_count = 0
        shortlisted = [post for _, _, _, post in scored]
        candidate_cap = self.screen_max_llm_candidates_per_run if max_candidates is None else max(0, int(max_candidates))
        if candidate_cap > 0 and len(shortlisted) > candidate_cap:
            capped_count = len(shortlisted) - candidate_cap
            shortlisted = shortlisted[:candidate_cap]
        return shortlisted, {
            "screen_rule_dropped_count": rule_dropped_count,
            "screen_kept_count": kept_count,
            "screen_capped_count": capped_count,
            "screen_high_recall_candidate_count": high_recall_candidate_count,
            "screen_semantic_candidate_count": 0,
            "screen_semantic_scored_count": 0,
            "screen_semantic_dropped_count": 0,
            "screen_semantic_rescued_count": 0,
        }

    async def semantic_candidate_posts(
        self,
        posts: list[Post],
        *,
        embedder: Any | None,
        max_candidates: int,
        min_similarity: float,
        max_pool: int = 200,
    ) -> tuple[list[Post], dict[str, Any]]:
        """Select supplemental candidates by semantic similarity to pain-query prototypes."""
        if embedder is None or max_candidates <= 0 or not posts or not self.semantic_candidate_queries:
            return [], {
                "screen_semantic_candidate_count": 0,
                "screen_semantic_scored_count": 0,
                "screen_semantic_dropped_count": 0,
                "screen_semantic_rescued_count": 0,
                "screen_semantic_max_similarity": 0.0,
            }

        pool = list(posts)
        pool.sort(key=lambda post: (self.operational_consequence_score(post), self.prescreen_score(post)), reverse=True)
        if max_pool > 0:
            pool = pool[:max_pool]

        query_vectors = await embedder.embed_many(self.semantic_candidate_queries)
        scored: list[tuple[float, int, int, Post]] = []
        max_similarity = 0.0
        for index, post in enumerate(pool):
            vector = await embedder.embed(self.candidate_text(post))
            similarity = max((cosine_similarity(vector, query_vector) for query_vector in query_vectors), default=0.0)
            max_similarity = max(max_similarity, similarity)
            if similarity >= min_similarity:
                scored.append((similarity, self.operational_consequence_score(post), -index, post))

        scored.sort(key=lambda item: (item[0], item[1], item[2]), reverse=True)
        shortlisted = [post for _, _, _, post in scored[:max_candidates]]
        return shortlisted, {
            "screen_semantic_candidate_count": len(shortlisted),
            "screen_semantic_scored_count": len(pool),
            "screen_semantic_dropped_count": max(0, len(pool) - len(scored)),
            "screen_semantic_rescued_count": len(shortlisted),
            "screen_semantic_max_similarity": round(max_similarity, 3),
        }

    async def select_candidates(
        self,
        posts: list[Post],
        *,
        max_candidates: int | None = None,
        semantic_embedder: Any | None = None,
        semantic_min_similarity: float = 0.22,
        semantic_max_candidates: int = 0,
        semantic_max_pool: int = 200,
    ) -> tuple[list[Post], dict[str, Any]]:
        self._semantic_rescue_post_ids = set()
        deterministic_posts, deterministic_stats = self.prescreen_posts(posts, max_candidates=0)
        deterministic_ids = {post.post_id for post in deterministic_posts}
        dropped_posts = [post for post in posts if post.post_id not in deterministic_ids]
        semantic_posts, semantic_stats = await self.semantic_candidate_posts(
            dropped_posts,
            embedder=semantic_embedder,
            max_candidates=semantic_max_candidates,
            min_similarity=max(0.0, min(1.0, float(semantic_min_similarity))),
            max_pool=max(0, int(semantic_max_pool)),
        )
        combined_by_id: dict[str, Post] = {post.post_id: post for post in deterministic_posts}
        semantic_rescue_ids: set[str] = set()
        for post in semantic_posts:
            if post.post_id not in combined_by_id:
                semantic_rescue_ids.add(post.post_id)
            combined_by_id.setdefault(post.post_id, post)
        combined = list(combined_by_id.values())
        combined.sort(key=lambda post: (self.prescreen_score(post), self.operational_consequence_score(post)), reverse=True)

        kept_count = len(combined)
        candidate_cap = self.screen_max_llm_candidates_per_run if max_candidates is None else max(0, int(max_candidates))
        capped_count = 0
        if candidate_cap > 0 and len(combined) > candidate_cap:
            capped_count = len(combined) - candidate_cap
            combined = combined[:candidate_cap]

        final_semantic_rescue_ids = {post.post_id for post in combined if post.post_id in semantic_rescue_ids}
        self._semantic_rescue_post_ids = final_semantic_rescue_ids

        stats = dict(deterministic_stats)
        stats.update(semantic_stats)
        stats["screen_rule_dropped_count"] = max(0, len(posts) - kept_count)
        stats["screen_kept_count"] = kept_count
        stats["screen_capped_count"] = capped_count
        stats["screen_semantic_rescued_count"] = len(final_semantic_rescue_ids)
        stats["screen_candidate_cap"] = candidate_cap
        return combined, stats

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

    @staticmethod
    def _body_without_appended_comments(body: str) -> str:
        marker = "\n\nTop comments:\n"
        if marker in body:
            return body.split(marker, 1)[0]
        if body.startswith("Top comments:\n"):
            return ""
        return body

    def _evidence_sources(self, post: Post) -> list[EvidenceSource]:
        sources: list[EvidenceSource] = []
        body_text = self._body_without_appended_comments(post.body)
        if post.title.strip():
            sources.append(
                EvidenceSource(
                    source_type="title",
                    text=post.title,
                    post_id=post.post_id,
                    permalink=post.url,
                    created_utc=post.source_created_ts,
                )
            )
        if body_text.strip():
            sources.append(
                EvidenceSource(
                    source_type="body",
                    text=body_text,
                    post_id=post.post_id,
                    permalink=post.url,
                    created_utc=post.source_created_ts,
                )
            )
        for index, comment in enumerate(post.top_comments or [], start=1):
            if not isinstance(comment, str) or not comment.strip():
                continue
            sources.append(
                EvidenceSource(
                    source_type="comment",
                    text=comment,
                    post_id=post.post_id,
                    comment_id=f"{post.post_id}:comment:{index}",
                    permalink=post.url,
                    created_utc=post.source_created_ts,
                )
            )
        return sources

    @staticmethod
    def _evidence_quality(verified_evidence: list[VerifiedEvidence]) -> tuple[str, float, str, bool]:
        if not verified_evidence:
            return "no_quote", 0.0, "No evidence spans were supplied by the analyzer.", True
        matched = [item for item in verified_evidence if item.match_type != "none"]
        matched_count = len(matched)
        match_rate = round(matched_count / len(verified_evidence), 3)
        if matched_count == 0:
            return "no_quote", 0.0, "No verified evidence matched the source text.", True
        exact_count = sum(1 for item in matched if item.match_type == "exact")
        if exact_count >= 2:
            quality = "multi_quote"
        elif exact_count == 1:
            quality = "exact_quote"
        else:
            quality = "weak_quote"
        unmatched_count = len(verified_evidence) - matched_count
        uncertainty = "" if unmatched_count == 0 else f"{unmatched_count} evidence span(s) did not match source text exactly."
        return quality, match_rate, uncertainty, match_rate < 0.5

    def _verify_evidence(self, post: Post, evidence_spans: list[str], result: AnalysisResult) -> tuple[list[VerifiedEvidence], str, float, float, str, bool]:
        verified_evidence = verify_evidence_spans(evidence_spans, self._evidence_sources(post))
        evidence_quality, evidence_match_rate, uncertainty_reason, needs_human_review = self._evidence_quality(verified_evidence)
        result_uncertainty = (result.uncertainty_reason or "").strip()
        if result_uncertainty and uncertainty_reason:
            uncertainty_reason = f"{result_uncertainty}; {uncertainty_reason}"
        elif result_uncertainty:
            uncertainty_reason = result_uncertainty
        confidence = result.confidence if result.confidence > 0 else evidence_match_rate
        needs_human_review = bool(result.needs_human_review) or needs_human_review
        return verified_evidence, evidence_quality, evidence_match_rate, confidence, uncertainty_reason, needs_human_review

    @staticmethod
    def _pain_detection_payload(result: PainDetectionResult) -> dict[str, Any]:
        return {
            "schema_version": "pain_detection_v1",
            "is_pain": result.is_pain,
            "is_noise": result.is_noise,
            "post_type": result.post_type,
            "operational_consequence": result.operational_consequence,
            "confidence": result.confidence,
            "uncertainty_reason": result.uncertainty_reason,
            "needs_human_review": result.needs_human_review,
        }

    @staticmethod
    def _attach_pain_detection_payload(signal: PainSignal, result: PainDetectionResult | None) -> PainSignal:
        if result is None:
            return signal
        primary_payload: dict[str, Any]
        if isinstance(signal.analysis_payload, dict):
            primary_payload = dict(signal.analysis_payload)
        else:
            primary_payload = {
                "summary": signal.summary,
                "category": signal.category,
                "severity": signal.severity,
                "analysis_mode": signal.analysis_mode,
            }
        signal.analysis_payload = {
            "pain_detection": Classifier._pain_detection_payload(result),
            "primary": primary_payload,
        }
        return signal

    def _signal_from_analysis(self, post: Post, result: AnalysisResult, mode: str) -> PainSignal:
        pain_level = max(0, min(10, int(result.pain_level)))
        willingness_to_pay = max(0, min(10, int(result.willingness_to_pay)))
        intensity = max(0, min(10, int(result.intensity)))
        frequency = max(0, min(10, int(result.frequency)))
        urgency = max(0, min(10, int(result.urgency)))
        inferred_post_type = result.post_type or self._infer_post_type(post, category=result.category)
        if result.evidence_spans:
            evidence_spans = list(result.evidence_spans)
        elif mode == "legacy_llm":
            evidence_spans = self._extract_evidence_spans(post)
        else:
            evidence_spans = []
        (
            verified_evidence,
            evidence_quality,
            evidence_match_rate,
            confidence,
            uncertainty_reason,
            needs_human_review,
        ) = self._verify_evidence(post, evidence_spans, result)
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
            pain_type=result.pain_type,
            expression_type=result.expression_type,
            user_context=result.user_context,
            user_context_json=self._user_context_payload(result),
            intensity=intensity,
            intensity_score=round(intensity / 10, 3) if intensity else round(pain_level / 10, 3),
            frequency=frequency,
            frequency_signal=self._frequency_signal(frequency),
            urgency=urgency,
            current_workaround=result.current_workaround,
            wtp_score=round(willingness_to_pay / 10, 3),
            incumbent_failure=result.incumbent_failure,
            evidence_spans=evidence_spans,
            opportunity_type=result.opportunity_type,
            verified_evidence=verified_evidence,
            evidence_quality=evidence_quality,
            evidence_match_rate=evidence_match_rate,
            confidence=confidence,
            uncertainty_reason=uncertainty_reason,
            needs_human_review=needs_human_review,
        )

    @staticmethod
    def _user_context_payload(result: AnalysisResult) -> dict[str, Any]:
        payload = result.raw_payload if isinstance(result.raw_payload, dict) else {}
        raw_context = payload.get("user_context_json")
        if isinstance(raw_context, dict):
            return {str(key): value for key, value in raw_context.items() if str(key).strip()}
        user_context = str(result.user_context or "").strip()
        return {"description": user_context} if user_context else {}

    @staticmethod
    def _frequency_signal(frequency: int) -> str:
        if frequency >= 8:
            return "trend"
        if frequency >= 6:
            return "repeated_cross_thread"
        if frequency >= 3:
            return "thread_consensus"
        return "single"

    async def classify(self, post: Post) -> PainSignal | None:
        keyword_score = self.keyword_score(post)
        rule_score = self.prescreen_score(post)
        semantic_rescue = post.post_id in self._semantic_rescue_post_ids
        if rule_score < self.screen_min_rule_score and not semantic_rescue:
            return None

        heuristic_score = max(keyword_score, min(3, rule_score))
        b2c_noise = self._is_likely_b2c_noise(post)
        dspy_attempted = False
        primary_attempted = False
        pain_detection_result: PainDetectionResult | None = None

        if self.mode in {"b2b", "dual"}:
            if self.staged_pain_detection_enabled and self.openrouter is not None:
                pain_detection_result = await self.openrouter.analyze_pain_detection(
                    title=post.title,
                    body=post.body,
                    post_id=post.post_id,
                )
                if pain_detection_result is None or pain_detection_result.is_noise or not pain_detection_result.is_pain:
                    return None
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
                    return self._attach_pain_detection_payload(signal, pain_detection_result)
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
                    return self._attach_pain_detection_payload(signal, pain_detection_result)
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
                return self._attach_pain_detection_payload(signal, pain_detection_result)

        if self.mode == "b2b":
            return None

        category = self._keyword_category(post)
        inferred_post_type = self._infer_post_type(post, category=category)
        evidence_spans = self._extract_evidence_spans(post)
        verified_evidence = verify_evidence_spans(evidence_spans, self._evidence_sources(post))
        evidence_quality, evidence_match_rate, uncertainty_reason, needs_human_review = self._evidence_quality(verified_evidence)
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
            evidence_spans=evidence_spans,
            verified_evidence=verified_evidence,
            evidence_quality=evidence_quality,
            evidence_match_rate=evidence_match_rate,
            confidence=evidence_match_rate,
            uncertainty_reason=uncertainty_reason,
            needs_human_review=needs_human_review,
        )

    async def classify_batch(self, posts: list[Post]) -> list[PainSignal]:
        semaphore = asyncio.Semaphore(self.max_concurrency)

        async def _classify_with_limit(post: Post) -> PainSignal | None:
            async with semaphore:
                return await self.classify(post)

        signals = await asyncio.gather(*(_classify_with_limit(post) for post in posts))
        self._semantic_rescue_post_ids.difference_update(post.post_id for post in posts)
        return [s for s in signals if s is not None]
