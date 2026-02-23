import logging
from dataclasses import dataclass
from typing import Optional
from scraper import Post
from openrouter import OpenRouterClient, AnalysisResult

logger = logging.getLogger(__name__)

COMPLAINT_WORDS = [
    "can't", "cannot", "broken", "frustrated", "frustrating",
    "annoying", "hate", "terrible", "awful", "useless", "fail",
    "failing", "doesn't work", "won't work", "keeps crashing",
    "impossible", "so bad", "worst",
]

UNSOLVED_WORDS = [
    "how do i", "how can i", "help me", "stuck on", "can't figure",
    "anyone know", "is there a way", "not sure how", "struggling with",
]

WISH_WORDS = [
    "wish", "would be nice", "feature request", "please add",
    "why doesn't", "why can't", "should have", "needs to have",
    "lacks", "missing",
]


@dataclass
class PainSignal:
    post: Post
    category: str
    summary: str
    severity: str


class Classifier:
    def __init__(self, openrouter: Optional[OpenRouterClient]):
        self.openrouter = openrouter

    def keyword_score(self, post: Post) -> int:
        text = f"{post.title} {post.body}".lower()
        score = 0
        if any(w in text for w in COMPLAINT_WORDS):
            score += 2
        if any(w in text for w in UNSOLVED_WORDS):
            score += 1
        if any(w in text for w in WISH_WORDS):
            score += 1
        return min(score, 3)

    def _keyword_category(self, post: Post) -> str:
        text = f"{post.title} {post.body}".lower()
        if any(w in text for w in WISH_WORDS):
            return "wish"
        if any(w in text for w in UNSOLVED_WORDS):
            return "unsolved"
        return "complaint"

    async def classify(self, post: Post) -> Optional[PainSignal]:
        score = self.keyword_score(post)
        if score == 0:
            return None

        if self.openrouter:
            result: Optional[AnalysisResult] = await self.openrouter.analyze_post(
                title=post.title, body=post.body
            )
            if result:
                return PainSignal(
                    post=post,
                    category=result.category,
                    summary=result.summary,
                    severity=result.severity,
                )

        # Fallback: rule-based
        return PainSignal(
            post=post,
            category=self._keyword_category(post),
            summary=post.title[:120],
            severity="medium" if score >= 2 else "low",
        )

    async def classify_batch(self, posts: list[Post]) -> list[PainSignal]:
        results = []
        for post in posts:
            signal = await self.classify(post)
            if signal:
                results.append(signal)
        return results
