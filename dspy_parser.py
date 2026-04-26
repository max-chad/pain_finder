from __future__ import annotations

import asyncio
import json
import logging
import math
import re
from typing import Any

from openrouter import (
    AnalysisResult,
    VALID_BUYER_AUTHORITIES,
    VALID_CATEGORIES,
    VALID_FIRST_HANDNESS,
    VALID_POST_TYPES,
    VALID_SEVERITIES,
)
from scraper import Post

logger = logging.getLogger(__name__)


class DSPyRedditPainParser:
    def __init__(
        self,
        *,
        api_key: str,
        provider: str = "codex",
        model: str = "gpt-5.3-spark",
        api_base: str = "",
        reasoning_effort: str = "high",
        temperature: float = 1.0,
        max_tokens: int = 16000,
    ) -> None:
        self.api_key = api_key.strip()
        self.provider = provider.strip().lower() or "codex"
        self.model = model.strip() or "gpt-5.3-spark"
        self.api_base = api_base.strip()
        self.reasoning_effort = reasoning_effort.strip().lower() or "high"
        self.temperature = temperature
        self.max_tokens = max_tokens
        self._dspy: Any | None = None
        self._lm: Any | None = None
        self._program: Any | None = None

    def _model_name_for_provider(self) -> str:
        normalized = self.provider
        if normalized in {"codex", "openai", "openrouter"}:
            return f"openai/{self.model}"
        return f"{normalized}/{self.model}"

    def _lm_kwargs(self) -> dict[str, Any]:
        kwargs: dict[str, Any] = {
            "api_key": self.api_key,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
        }
        if self.reasoning_effort:
            kwargs["reasoning_effort"] = self.reasoning_effort

        if self.provider == "openrouter":
            kwargs["api_base"] = self.api_base or "https://openrouter.ai/api/v1"
            kwargs["extra_headers"] = {
                "HTTP-Referer": "https://github.com/max-chad/pain_finder",
                "X-Title": "pain_finder",
            }
        elif self.api_base:
            kwargs["api_base"] = self.api_base
        return kwargs

    def _ensure_program(self) -> Any:
        if self._program is not None and self._dspy is not None and self._lm is not None:
            return self._program

        import dspy

        class RedditPainSignature(dspy.Signature):
            """Extract monetizable B2B pain signals from Reddit posts and thread context."""

            subreddit = dspy.InputField(desc="Subreddit name without the r/ prefix")
            title = dspy.InputField(desc="Reddit post title")
            body = dspy.InputField(desc="Reddit self text with any appended comment context")
            top_comments = dspy.InputField(desc="newline separated top comments, may be empty")
            discovery_query = dspy.InputField(desc="search query that surfaced the post, may be empty")

            category = dspy.OutputField(desc="one of complaint, unsolved, wish")
            severity = dspy.OutputField(desc="one of low, medium, high")
            is_monetizable = dspy.OutputField(desc="true or false")
            pain_level = dspy.OutputField(desc="integer 0..10")
            willingness_to_pay = dspy.OutputField(desc="integer 0..10")
            niche_category = dspy.OutputField(desc="short B2B niche category")
            competitor_tags_csv = dspy.OutputField(desc="comma-separated lowercase software tags")
            summary = dspy.OutputField(desc="one-sentence summary of the pain")
            post_type = dspy.OutputField(
                desc="one of first_person_pain, solution_request, founder_pitch, news_analysis, tool_comparison, advice_thread, vendor_rant"
            )
            first_handness = dspy.OutputField(desc="one of first_hand, second_hand, aggregated, speculative, unknown")
            buyer_authority = dspy.OutputField(
                desc="one of intern, ic, engineer, manager, head_of_ops, founder_owner, agency_operator, unknown"
            )
            evidence_spans = dspy.OutputField(desc="1-3 short exact quotes copied from title, body, or comments")
            confidence = dspy.OutputField(desc="number 0..1 for classification confidence after reading evidence")
            uncertainty_reason = dspy.OutputField(desc="short reason when confidence/evidence is ambiguous, else empty")
            needs_human_review = dspy.OutputField(desc="true if evidence is missing/ambiguous or confidence is low")

        lm = dspy.LM(self._model_name_for_provider(), **self._lm_kwargs())
        program = dspy.ChainOfThought(RedditPainSignature)

        self._dspy = dspy
        self._lm = lm
        self._program = program
        return program

    async def analyze_post(self, post: Post) -> AnalysisResult | None:
        if not self.api_key:
            logger.warning("DSPy Reddit parser is enabled but no API key was provided")
            return None

        try:
            program = self._ensure_program()
            assert self._dspy is not None
            assert self._lm is not None

            def _run_program() -> Any:
                assert self._dspy is not None
                assert self._lm is not None
                with self._dspy.settings.context(lm=self._lm):
                    return program(
                        subreddit=post.subreddit,
                        title=post.title,
                        body=post.body,
                        top_comments="\n".join(post.top_comments),
                        discovery_query=post.discovery_query,
                    )

            prediction = await asyncio.to_thread(_run_program)
            return self._coerce_prediction(prediction)
        except Exception as exc:
            logger.warning("DSPy Reddit parser failed for %s: %s", post.post_id, exc)
            return None

    def _coerce_prediction(self, prediction: Any) -> AnalysisResult | None:
        category = self._string_field(prediction, "category")
        severity = self._string_field(prediction, "severity")
        summary = self._string_field(prediction, "summary")
        niche_category = self._string_field(prediction, "niche_category")
        is_monetizable = self._bool_field(prediction, "is_monetizable")
        pain_level = self._int_field(prediction, "pain_level")
        willingness_to_pay = self._int_field(prediction, "willingness_to_pay")
        competitor_tags = self._competitor_tags(prediction)
        post_type = self._choice_field(prediction, "post_type", VALID_POST_TYPES, fallback="advice_thread")
        first_handness = self._choice_field(prediction, "first_handness", VALID_FIRST_HANDNESS, fallback="unknown")
        buyer_authority = self._choice_field(prediction, "buyer_authority", VALID_BUYER_AUTHORITIES, fallback="unknown")
        evidence_spans = self._evidence_spans(prediction)
        confidence = self._confidence_field(prediction, "confidence")
        uncertainty_reason = self._string_field(prediction, "uncertainty_reason")[:240]
        needs_human_review = self._bool_field(prediction, "needs_human_review")

        if category not in VALID_CATEGORIES:
            return None
        if severity not in VALID_SEVERITIES:
            return None
        if not summary:
            return None
        if is_monetizable is None:
            return None
        if pain_level is None or not (0 <= pain_level <= 10):
            return None
        if willingness_to_pay is None or not (0 <= willingness_to_pay <= 10):
            return None
        if post_type is None or first_handness is None or buyer_authority is None:
            return None
        if confidence is None:
            confidence = 0.0
        if needs_human_review is None:
            needs_human_review = not evidence_spans or confidence < 0.5

        raw_payload = {
            "category": category,
            "severity": severity,
            "summary": summary,
            "is_monetizable": is_monetizable,
            "pain_level": pain_level,
            "willingness_to_pay": willingness_to_pay,
            "niche_category": niche_category,
            "competitor_tags": competitor_tags,
            "post_type": post_type,
            "first_handness": first_handness,
            "buyer_authority": buyer_authority,
            "evidence_spans": evidence_spans,
            "confidence": confidence,
            "uncertainty_reason": uncertainty_reason,
            "needs_human_review": needs_human_review,
        }
        return AnalysisResult(
            category=category,
            summary=summary,
            severity=severity,
            is_monetizable=is_monetizable,
            pain_level=pain_level,
            willingness_to_pay=willingness_to_pay if is_monetizable else min(willingness_to_pay, 3),
            niche_category=niche_category,
            competitor_tags=competitor_tags,
            post_type=post_type,
            first_handness=first_handness,
            buyer_authority=buyer_authority,
            evidence_spans=evidence_spans,
            confidence=confidence,
            uncertainty_reason=uncertainty_reason,
            needs_human_review=needs_human_review,
            raw_payload=raw_payload,
        )

    @staticmethod
    def _get_value(prediction: Any, field_name: str) -> Any:
        if isinstance(prediction, dict):
            return prediction.get(field_name)
        return getattr(prediction, field_name, None)

    def _string_field(self, prediction: Any, field_name: str) -> str:
        value = self._get_value(prediction, field_name)
        if value is None:
            return ""
        return str(value).strip()

    def _bool_field(self, prediction: Any, field_name: str) -> bool | None:
        value = self._get_value(prediction, field_name)
        if isinstance(value, bool):
            return value
        if value is None:
            return None
        normalized = str(value).strip().lower()
        if normalized in {"true", "yes", "1"}:
            return True
        if normalized in {"false", "no", "0"}:
            return False
        return None

    def _int_field(self, prediction: Any, field_name: str) -> int | None:
        value = self._get_value(prediction, field_name)
        if isinstance(value, bool) or value is None:
            return None
        try:
            return int(str(value).strip())
        except (TypeError, ValueError):
            return None

    def _choice_field(self, prediction: Any, field_name: str, allowed: set[str], *, fallback: str) -> str | None:
        value = self._get_value(prediction, field_name)
        if value is None or str(value).strip() == "":
            return fallback
        normalized = str(value).strip()
        return normalized if normalized in allowed else None

    def _confidence_field(self, prediction: Any, field_name: str) -> float | None:
        value = self._get_value(prediction, field_name)
        if value is None or isinstance(value, bool):
            return None
        try:
            numeric = float(str(value).strip())
        except (TypeError, ValueError):
            return None
        if not math.isfinite(numeric):
            return None
        return round(max(0.0, min(1.0, numeric)), 3)

    def _evidence_spans(self, prediction: Any) -> list[str]:
        value = self._get_value(prediction, "evidence_spans")
        if value is None:
            return []
        if isinstance(value, str):
            raw_text = value.strip()
            if not raw_text:
                return []
            try:
                parsed = json.loads(raw_text)
            except json.JSONDecodeError:
                parsed = None
            if isinstance(parsed, list):
                raw_items = parsed
            else:
                raw_items = [line for line in re.split(r"[\n;]+", raw_text) if line]
        elif isinstance(value, list | tuple):
            raw_items = list(value)
        else:
            return []

        output: list[str] = []
        seen: set[str] = set()
        for item in raw_items:
            clean = str(item).strip()[:160]
            if not clean or clean in seen:
                continue
            seen.add(clean)
            output.append(clean)
            if len(output) >= 3:
                break
        return output

    def _competitor_tags(self, prediction: Any) -> list[str]:
        value = self._get_value(prediction, "competitor_tags_csv")
        if value is None:
            return []
        if isinstance(value, list):
            raw_items = value
        else:
            raw_items = str(value).split(",")

        output: list[str] = []
        seen: set[str] = set()
        for item in raw_items:
            clean = str(item).strip().lower()
            if not clean or clean in seen:
                continue
            seen.add(clean)
            output.append(clean)
        return output
