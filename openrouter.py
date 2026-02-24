import asyncio
import json
import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import httpx

if TYPE_CHECKING:
    from budget import BudgetGuard

logger = logging.getLogger(__name__)

VALID_CATEGORIES = {"complaint", "unsolved", "wish"}
VALID_SEVERITIES = {"low", "medium", "high"}
VALID_SIGNAL_LEVELS = {"low", "medium", "high"}
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}
RETRY_BACKOFF_SECONDS = (0.5, 1.0, 2.0)

PRIMARY_PROMPT_TEMPLATE = """You are a B2B SaaS product manager analyzing Reddit pain signals.

Task:
1. Determine if this pain is monetizable for a business software product.
2. Score pain intensity and willingness to pay.
3. Categorize the niche.
4. Extract competitor software names mentioned negatively.
5. Keep compatibility fields (category, severity).

Reject non-business consumer venting as non-monetizable with low scores.

Return ONLY valid JSON with this exact schema:
{
  "is_monetizable": true,
  "pain_level": 1,
  "willingness_to_pay": 1,
  "niche_category": "E-commerce",
  "competitor_tags": ["shopify", "quickbooks"],
  "summary": "One sentence summary",
  "category": "complaint",
  "severity": "low"
}

Rules:
- pain_level: integer 0..10
- willingness_to_pay: integer 0..10
- competitor_tags: array of lowercase software tags, empty array if none

Title: {title}
Body: {body}
"""

LEGACY_PROMPT_TEMPLATE = """Analyze this post and extract pain point JSON:
{
  "category": "complaint",
  "summary": "one sentence summary",
  "severity": "low"
}

Title: {title}
Body: {body}
"""

DEEP_DIVE_PROMPT_TEMPLATE = """Extract high-value B2B discovery notes from thread context.

Return ONLY JSON:
{
  "workarounds": ["..."],
  "competitors": ["..."],
  "feature_wishlist": ["..."],
  "buying_signals": ["..."],
  "icp_hypothesis": "...",
  "actionable_summary": "..."
}

Title: {title}
Thread:
{thread_text}
"""

CLUSTER_LABEL_PROMPT_TEMPLATE = """You are labeling a grouped cluster of similar customer complaints.

Return ONLY JSON:
{
  "label": "short trend title",
  "summary": "macro summary in 1-2 sentences",
  "estimated_monetization_signal": "low",
  "key_complaints": ["...", "..."]
}

Cluster size: {cluster_size}
Examples:
{cluster_text}
"""

GTM_PROMPT_TEMPLATE = """You are a startup founder generating immediate GTM validation assets.

Return ONLY JSON:
{
  "name_options": ["name 1", "name 2", "name 3"],
  "hero_h1": "...",
  "hero_h2": "...",
  "mvp_features": ["...", "...", "..."],
  "pricing_tier": "...",
  "positioning_rationale": "..."
}

Context:
{context}
"""


@dataclass
class UsageEvent:
    model: str
    operation: str
    prompt_tokens: int
    completion_tokens: int
    cost_usd: float
    post_id: str | None = None


@dataclass
class AnalysisResult:
    category: str
    summary: str
    severity: str
    is_monetizable: bool = False
    pain_level: int = 0
    willingness_to_pay: int = 0
    niche_category: str = ""
    competitor_tags: list[str] = field(default_factory=list)
    raw_payload: dict[str, Any] | None = None


@dataclass
class DeepDiveResult:
    workarounds: list[str]
    competitors: list[str]
    feature_wishlist: list[str]
    buying_signals: list[str]
    icp_hypothesis: str
    actionable_summary: str
    raw_payload: dict[str, Any] | None = None


@dataclass
class MacroClusterLabel:
    label: str
    summary: str
    estimated_monetization_signal: str
    key_complaints: list[str]
    raw_payload: dict[str, Any] | None = None


@dataclass
class GTMGenerationResult:
    name_options: list[str]
    hero_h1: str
    hero_h2: str
    mvp_features: list[str]
    pricing_tier: str
    positioning_rationale: str
    raw_payload: dict[str, Any] | None = None


class OpenRouterClient:
    BASE_URL = "https://openrouter.ai/api/v1/chat/completions"

    def __init__(
        self,
        api_key: str,
        model: str,
        deep_dive_model: str | None = None,
        cluster_model: str | None = None,
        gtm_model: str | None = None,
        pricing_map: dict[str, dict[str, float]] | None = None,
        budget_guard: "BudgetGuard | None" = None,
    ):
        self.api_key = api_key
        self.model = model
        self.deep_dive_model = deep_dive_model or model
        self.cluster_model = cluster_model or model
        self.gtm_model = gtm_model or model
        self.pricing_map = pricing_map or {}
        self.budget_guard = budget_guard

    def set_budget_guard(self, budget_guard: "BudgetGuard | None") -> None:
        self.budget_guard = budget_guard

    async def analyze_post(self, title: str, body: str, post_id: str | None = None) -> AnalysisResult | None:
        prompt = PRIMARY_PROMPT_TEMPLATE.replace("{title}", title).replace("{body}", body[:5000])
        payload = await self._request_json_response(
            prompt=prompt,
            model=self.model,
            operation="classify_primary",
            post_id=post_id,
        )
        if payload is None:
            return None
        result = self._parse_primary_result(payload)
        if result is None:
            logger.warning("OpenRouter primary output failed validation: %s", payload)
        return result

    async def analyze_legacy_post(self, title: str, body: str, post_id: str | None = None) -> AnalysisResult | None:
        prompt = LEGACY_PROMPT_TEMPLATE.replace("{title}", title).replace("{body}", body[:4000])
        payload = await self._request_json_response(
            prompt=prompt,
            model=self.model,
            operation="classify_legacy",
            post_id=post_id,
        )
        if payload is None:
            return None
        result = self._parse_legacy_result(payload)
        if result is None:
            logger.warning("OpenRouter legacy output failed validation: %s", payload)
        return result

    async def analyze_deep_dive(self, title: str, thread_text: str, post_id: str | None = None) -> DeepDiveResult | None:
        prompt = DEEP_DIVE_PROMPT_TEMPLATE.replace("{title}", title).replace("{thread_text}", thread_text[:25000])
        payload = await self._request_json_response(
            prompt=prompt,
            model=self.deep_dive_model,
            operation="deep_dive",
            post_id=post_id,
        )
        if payload is None:
            return None
        result = self._parse_deep_dive_result(payload)
        if result is None:
            logger.warning("OpenRouter deep dive output failed validation: %s", payload)
        return result

    async def label_macro_cluster(
        self,
        *,
        cluster_text: str,
        cluster_size: int,
        post_id: str | None = None,
    ) -> MacroClusterLabel | None:
        prompt = CLUSTER_LABEL_PROMPT_TEMPLATE.replace("{cluster_text}", cluster_text[:12000]).replace(
            "{cluster_size}", str(cluster_size)
        )
        payload = await self._request_json_response(
            prompt=prompt,
            model=self.cluster_model,
            operation="cluster_label",
            post_id=post_id,
        )
        if payload is None:
            return None
        result = self._parse_cluster_label(payload)
        if result is None:
            logger.warning("OpenRouter cluster labeling failed validation: %s", payload)
        return result

    async def generate_gtm(self, context: str, post_id: str | None = None) -> GTMGenerationResult | None:
        prompt = GTM_PROMPT_TEMPLATE.replace("{context}", context[:18000])
        payload = await self._request_json_response(
            prompt=prompt,
            model=self.gtm_model,
            operation="generate_gtm",
            post_id=post_id,
        )
        if payload is None:
            return None
        result = self._parse_gtm_result(payload)
        if result is None:
            logger.warning("OpenRouter GTM output failed validation: %s", payload)
        return result

    async def _request_json_response(
        self,
        *,
        prompt: str,
        model: str,
        operation: str,
        post_id: str | None,
    ) -> dict[str, Any] | None:
        if self.budget_guard is not None:
            await self.budget_guard.ensure_can_spend(operation)

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        request_body = {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.1,
            "response_format": {"type": "json_object"},
        }

        _max_attempts = len(RETRY_BACKOFF_SECONDS)
        try:
            async with httpx.AsyncClient(timeout=45) as client:
                for attempt in range(1, _max_attempts + 1):
                    try:
                        response = await client.post(self.BASE_URL, json=request_body, headers=headers)
                        response.raise_for_status()
                        response_json = response.json()
                        content = response_json["choices"][0]["message"]["content"]
                        payload = self._safe_json_load(content)
                        await self._record_usage_from_response(
                            response_json=response_json,
                            model=model,
                            operation=operation,
                            post_id=post_id,
                        )
                        return payload
                    except httpx.HTTPStatusError as e:
                        status_code = e.response.status_code if e.response else None
                        if status_code in RETRYABLE_STATUS_CODES and attempt < _max_attempts:
                            delay = RETRY_BACKOFF_SECONDS[attempt - 1]
                            logger.warning(
                                "OpenRouter HTTP %s attempt %d/%d model=%s operation=%s retry=%.1fs",
                                status_code,
                                attempt,
                                _max_attempts,
                                model,
                                operation,
                                delay,
                            )
                            await asyncio.sleep(delay)
                            continue
                        raise
                    except httpx.RequestError as e:
                        if attempt < _max_attempts:
                            delay = RETRY_BACKOFF_SECONDS[attempt - 1]
                            logger.warning(
                                "OpenRouter request error %s attempt %d/%d model=%s operation=%s retry=%.1fs",
                                e,
                                attempt,
                                _max_attempts,
                                model,
                                operation,
                                delay,
                            )
                            await asyncio.sleep(delay)
                            continue
                        raise
        except (httpx.HTTPError, KeyError, IndexError, json.JSONDecodeError) as e:
            logger.warning("OpenRouter request failed: %s", e)
            return None

    async def _record_usage_from_response(
        self,
        *,
        response_json: dict[str, Any],
        model: str,
        operation: str,
        post_id: str | None,
    ) -> None:
        usage = response_json.get("usage")
        if not isinstance(usage, dict):
            return

        prompt_tokens = int(usage.get("prompt_tokens", 0) or 0)
        completion_tokens = int(usage.get("completion_tokens", 0) or 0)
        cost_usd = self._estimate_cost_usd(model, prompt_tokens, completion_tokens)

        if self.budget_guard is not None:
            await self.budget_guard.record_usage(
                model=model,
                operation=operation,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                cost_usd=cost_usd,
                post_id=post_id,
            )

    def _estimate_cost_usd(self, model: str, prompt_tokens: int, completion_tokens: int) -> float:
        pricing = self.pricing_map.get(model, {})
        prompt_per_1k = float(pricing.get("prompt_per_1k", 0) or 0)
        completion_per_1k = float(pricing.get("completion_per_1k", 0) or 0)
        prompt_cost = (prompt_tokens / 1000.0) * prompt_per_1k
        completion_cost = (completion_tokens / 1000.0) * completion_per_1k
        return round(prompt_cost + completion_cost, 8)

    @staticmethod
    def _safe_json_load(raw_content: str) -> dict[str, Any]:
        content = raw_content.strip()
        if content.startswith("```"):
            content = content.strip("`")
            if content.lower().startswith("json"):
                content = content[4:].strip()
        parsed = json.loads(content)
        if not isinstance(parsed, dict):
            raise json.JSONDecodeError("Response is not JSON object", content, 0)
        return parsed

    def _parse_primary_result(self, payload: dict[str, Any]) -> AnalysisResult | None:
        category = payload.get("category")
        severity = payload.get("severity")
        summary = payload.get("summary")
        monetizable = payload.get("is_monetizable")
        pain_level = payload.get("pain_level")
        willingness_to_pay = payload.get("willingness_to_pay")
        niche_category = payload.get("niche_category")
        competitor_tags = payload.get("competitor_tags", [])

        if category not in VALID_CATEGORIES:
            return None
        if severity not in VALID_SEVERITIES:
            return None
        if not isinstance(summary, str) or not summary.strip():
            return None
        if not isinstance(monetizable, bool):
            return None
        if not isinstance(pain_level, int) or not (0 <= pain_level <= 10):
            return None
        if not isinstance(willingness_to_pay, int) or not (0 <= willingness_to_pay <= 10):
            return None
        if not isinstance(niche_category, str):
            return None
        if not isinstance(competitor_tags, list) or any(not isinstance(item, str) for item in competitor_tags):
            return None

        return AnalysisResult(
            category=category,
            summary=summary.strip(),
            severity=severity,
            is_monetizable=monetizable,
            pain_level=pain_level,
            willingness_to_pay=willingness_to_pay if monetizable else min(willingness_to_pay, 3),
            niche_category=niche_category.strip(),
            competitor_tags=[item.strip().lower() for item in competitor_tags if item.strip()],
            raw_payload=payload,
        )

    def _parse_legacy_result(self, payload: dict[str, Any]) -> AnalysisResult | None:
        category = payload.get("category")
        severity = payload.get("severity")
        summary = payload.get("summary")
        competitor_tags = payload.get("competitor_tags", [])

        if category not in VALID_CATEGORIES:
            return None
        if severity not in VALID_SEVERITIES:
            return None
        if not isinstance(summary, str) or not summary.strip():
            return None
        if not isinstance(competitor_tags, list) or any(not isinstance(item, str) for item in competitor_tags):
            competitor_tags = []

        return AnalysisResult(
            category=category,
            summary=summary.strip(),
            severity=severity,
            competitor_tags=[item.strip().lower() for item in competitor_tags if isinstance(item, str) and item.strip()],
            raw_payload=payload,
        )

    def _parse_deep_dive_result(self, payload: dict[str, Any]) -> DeepDiveResult | None:
        list_keys = ["workarounds", "competitors", "feature_wishlist", "buying_signals"]
        for key in list_keys:
            value = payload.get(key)
            if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
                return None

        icp_hypothesis = payload.get("icp_hypothesis")
        actionable_summary = payload.get("actionable_summary")
        if not isinstance(icp_hypothesis, str) or not icp_hypothesis.strip():
            return None
        if not isinstance(actionable_summary, str) or not actionable_summary.strip():
            return None

        return DeepDiveResult(
            workarounds=[item.strip() for item in payload["workarounds"] if item.strip()],
            competitors=[item.strip() for item in payload["competitors"] if item.strip()],
            feature_wishlist=[item.strip() for item in payload["feature_wishlist"] if item.strip()],
            buying_signals=[item.strip() for item in payload["buying_signals"] if item.strip()],
            icp_hypothesis=icp_hypothesis.strip(),
            actionable_summary=actionable_summary.strip(),
            raw_payload=payload,
        )

    def _parse_cluster_label(self, payload: dict[str, Any]) -> MacroClusterLabel | None:
        label = payload.get("label")
        summary = payload.get("summary")
        signal = payload.get("estimated_monetization_signal")
        key_complaints = payload.get("key_complaints")

        if not isinstance(label, str) or not label.strip():
            return None
        if not isinstance(summary, str) or not summary.strip():
            return None
        if signal not in VALID_SIGNAL_LEVELS:
            return None
        if not isinstance(key_complaints, list) or any(not isinstance(item, str) for item in key_complaints):
            return None

        return MacroClusterLabel(
            label=label.strip(),
            summary=summary.strip(),
            estimated_monetization_signal=signal,
            key_complaints=[item.strip() for item in key_complaints if item.strip()],
            raw_payload=payload,
        )

    def _parse_gtm_result(self, payload: dict[str, Any]) -> GTMGenerationResult | None:
        name_options = payload.get("name_options")
        hero_h1 = payload.get("hero_h1")
        hero_h2 = payload.get("hero_h2")
        mvp_features = payload.get("mvp_features")
        pricing_tier = payload.get("pricing_tier")
        positioning = payload.get("positioning_rationale")

        if not isinstance(name_options, list) or len(name_options) != 3:
            return None
        if any(not isinstance(item, str) or not item.strip() for item in name_options):
            return None
        if not isinstance(hero_h1, str) or not hero_h1.strip():
            return None
        if not isinstance(hero_h2, str) or not hero_h2.strip():
            return None
        if not isinstance(mvp_features, list) or len(mvp_features) != 3:
            return None
        if any(not isinstance(item, str) or not item.strip() for item in mvp_features):
            return None
        if not isinstance(pricing_tier, str) or not pricing_tier.strip():
            return None
        if not isinstance(positioning, str) or not positioning.strip():
            return None

        return GTMGenerationResult(
            name_options=[item.strip() for item in name_options],
            hero_h1=hero_h1.strip(),
            hero_h2=hero_h2.strip(),
            mvp_features=[item.strip() for item in mvp_features],
            pricing_tier=pricing_tier.strip(),
            positioning_rationale=positioning.strip(),
            raw_payload=payload,
        )
