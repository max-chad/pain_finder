from __future__ import annotations

import asyncio
import hashlib
import importlib.util
import json
import logging
from typing import TYPE_CHECKING, Any

from budget import BudgetCapReachedError, BudgetGuard
from openrouter import AnalysisResult, OpenRouterUsageAccountingError, VALID_CATEGORIES, VALID_SEVERITIES
from scraper import Post

if TYPE_CHECKING:
    from budget import BudgetGuard

logger = logging.getLogger(__name__)


class _NullBudgetAdmission:
    async def __aenter__(self) -> "_NullBudgetAdmission":
        return self

    async def __aexit__(self, *_exc: object) -> None:
        return None


class DSPyRedditPainParser:
    @staticmethod
    def is_available() -> bool:
        return importlib.util.find_spec("dspy") is not None

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
        timeout_seconds: float = 60.0,
        budget_guard: "BudgetGuard | None" = None,
        pricing_map: dict[str, dict[str, float]] | None = None,
    ) -> None:
        self.api_key = api_key.strip()
        self.provider = provider.strip().lower() or "codex"
        self.model = model.strip() or "gpt-5.3-spark"
        self.api_base = api_base.strip()
        self.reasoning_effort = reasoning_effort.strip().lower() or "high"
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.timeout_seconds = max(0.1, float(timeout_seconds))
        self.budget_guard = budget_guard
        self.pricing_map = pricing_map or {}
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
            "timeout": self.timeout_seconds,
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

        lm = dspy.LM(self._model_name_for_provider(), **self._lm_kwargs())
        program = dspy.ChainOfThought(RedditPainSignature)

        self._dspy = dspy
        self._lm = lm
        self._program = program
        return program

    async def _admit_budget(self, operation: str) -> Any:
        if self.budget_guard is None:
            return _NullBudgetAdmission()

        if isinstance(self.budget_guard, BudgetGuard):
            return await self.budget_guard.admit(operation)

        await self.budget_guard.ensure_can_spend(operation)
        return _NullBudgetAdmission()

    async def analyze_post(self, post: Post) -> AnalysisResult | None:
        if not self.api_key:
            logger.warning("DSPy Reddit parser is enabled but no API key was provided")
            return None

        if self.budget_guard is not None:
            if not self._pricing_entry():
                logger.warning(
                    "DSPy Reddit parser disabled because no pricing is configured for model=%s",
                    self.model,
                )
                return None

        try:
            program = self._ensure_program()
            assert self._dspy is not None
            assert self._lm is not None
            prompt_text = self._usage_prompt_text(post)

            async with await self._admit_budget("dspy_analyze_post"):
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

                prediction = await asyncio.wait_for(asyncio.to_thread(_run_program), timeout=self.timeout_seconds)
                await self._record_usage(post=post, prompt_text=prompt_text, prediction=prediction)
            return self._coerce_prediction(prediction)
        except (BudgetCapReachedError, OpenRouterUsageAccountingError):
            raise
        except Exception as exc:
            logger.warning("DSPy Reddit parser failed for %s: %s", post.post_id, exc)
            return None

    def _pricing_entry(self) -> dict[str, float]:
        entry = self.pricing_map.get(self.model) or self.pricing_map.get(self._model_name_for_provider()) or {}
        return {
            "prompt_per_1k": float(entry.get("prompt_per_1k", 0) or 0),
            "completion_per_1k": float(entry.get("completion_per_1k", 0) or 0),
        } if entry else {}

    @staticmethod
    def _usage_token_count(value: Any) -> int:
        try:
            parsed = int(value)
        except (OverflowError, TypeError, ValueError):
            return 0
        return max(0, parsed)

    @staticmethod
    def _estimate_tokens(text: str) -> int:
        return max(1, (len(text) + 3) // 4)

    def _usage_prompt_text(self, post: Post) -> str:
        return "\n".join(
            [
                f"subreddit={post.subreddit}",
                f"title={post.title}",
                f"body={post.body}",
                "top_comments=" + "\n".join(post.top_comments),
                f"discovery_query={post.discovery_query}",
            ]
        )

    def _usage_from_lm_history(self) -> dict[str, int] | None:
        history = getattr(self._lm, "history", None)
        if not history:
            return None
        try:
            latest = history[-1]
        except (KeyError, IndexError, TypeError):
            return None
        return self._usage_from_object(latest)

    def _usage_from_object(self, value: Any) -> dict[str, int] | None:
        if value is None:
            return None
        usage = value.get("usage") if isinstance(value, dict) else getattr(value, "usage", None)
        if usage is None and not isinstance(value, dict):
            usage = getattr(value, "token_usage", None)
        if usage is not None:
            nested = self._usage_from_object(usage)
            if nested is not None:
                return nested

        prompt_tokens = self._usage_token_count(
            value.get("prompt_tokens", value.get("input_tokens", 0))
            if isinstance(value, dict)
            else getattr(value, "prompt_tokens", getattr(value, "input_tokens", 0))
        )
        completion_tokens = self._usage_token_count(
            value.get("completion_tokens", value.get("output_tokens", 0))
            if isinstance(value, dict)
            else getattr(value, "completion_tokens", getattr(value, "output_tokens", 0))
        )
        if prompt_tokens <= 0 and completion_tokens <= 0:
            return None
        return {"prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens}

    def _estimated_usage(self, *, prompt_text: str, prediction: Any) -> dict[str, int]:
        prediction_payload = {
            "category": self._string_field(prediction, "category"),
            "severity": self._string_field(prediction, "severity"),
            "summary": self._string_field(prediction, "summary"),
            "is_monetizable": self._string_field(prediction, "is_monetizable"),
            "pain_level": self._string_field(prediction, "pain_level"),
            "willingness_to_pay": self._string_field(prediction, "willingness_to_pay"),
            "niche_category": self._string_field(prediction, "niche_category"),
            "competitor_tags_csv": self._string_field(prediction, "competitor_tags_csv"),
        }
        return {
            "prompt_tokens": self._estimate_tokens(prompt_text),
            "completion_tokens": self._estimate_tokens(json.dumps(prediction_payload, ensure_ascii=False)),
        }

    def _estimate_cost_usd(self, *, prompt_tokens: int, completion_tokens: int) -> float:
        pricing = self._pricing_entry()
        prompt_cost = (prompt_tokens / 1000.0) * float(pricing.get("prompt_per_1k", 0) or 0)
        completion_cost = (completion_tokens / 1000.0) * float(pricing.get("completion_per_1k", 0) or 0)
        return round(prompt_cost + completion_cost, 8)

    async def _record_usage(self, *, post: Post, prompt_text: str, prediction: Any) -> None:
        if self.budget_guard is None:
            return
        usage = self._usage_from_lm_history() or self._estimated_usage(prompt_text=prompt_text, prediction=prediction)
        prompt_tokens = self._usage_token_count(usage.get("prompt_tokens", 0))
        completion_tokens = self._usage_token_count(usage.get("completion_tokens", 0))
        try:
            await self.budget_guard.record_usage(
                model=self.model,
                operation="dspy_analyze_post",
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                cost_usd=self._estimate_cost_usd(
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                ),
                post_id=post.post_id,
                prompt_hash=hashlib.sha256(prompt_text.encode("utf-8")).hexdigest(),
                schema_version="dspy_primary_v1",
                provider=self.provider,
                request_path=self.api_base or self._model_name_for_provider(),
                candidate_stage="primary_dspy",
            )
        except Exception as exc:
            logger.warning(
                "llm_usage_record_failed model=%s operation=%s post_id=%s error=%s",
                self.model,
                "dspy_analyze_post",
                post.post_id,
                exc,
            )
            raise OpenRouterUsageAccountingError(
                f"llm_usage_record_failed model={self.model} operation=dspy_analyze_post post_id={post.post_id}"
            ) from exc

    def _coerce_prediction(self, prediction: Any) -> AnalysisResult | None:
        category = self._string_field(prediction, "category")
        severity = self._string_field(prediction, "severity")
        summary = self._string_field(prediction, "summary")
        niche_category = self._string_field(prediction, "niche_category")
        is_monetizable = self._bool_field(prediction, "is_monetizable")
        pain_level = self._int_field(prediction, "pain_level")
        willingness_to_pay = self._int_field(prediction, "willingness_to_pay")
        competitor_tags = self._competitor_tags(prediction)

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

        raw_payload = {
            "category": category,
            "severity": severity,
            "summary": summary,
            "is_monetizable": is_monetizable,
            "pain_level": pain_level,
            "willingness_to_pay": willingness_to_pay,
            "niche_category": niche_category,
            "competitor_tags": competitor_tags,
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
