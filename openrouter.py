import asyncio
import base64
import hashlib
import json
import logging
from dataclasses import dataclass, field
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

import httpx
from openai import OpenAI

if TYPE_CHECKING:
    from budget import BudgetGuard

logger = logging.getLogger(__name__)


class OpenRouterUsageAccountingError(Exception):
    """Raised when usage accounting persistence fails."""


class _NullBudgetAdmission:
    async def __aenter__(self) -> "_NullBudgetAdmission":
        return self

    async def __aexit__(self, *_exc: object) -> None:
        return None


VALID_CATEGORIES = {"complaint", "unsolved", "wish"}
VALID_SEVERITIES = {"low", "medium", "high"}
VALID_SIGNAL_LEVELS = {"low", "medium", "high"}
VALID_POST_TYPES = {
    "first_person_pain",
    "solution_request",
    "founder_pitch",
    "news_analysis",
    "tool_comparison",
    "advice_thread",
    "vendor_rant",
}
VALID_FIRST_HANDNESS = {"first_hand", "second_hand", "aggregated", "speculative", "unknown"}
VALID_BUYER_AUTHORITIES = {
    "intern",
    "ic",
    "engineer",
    "manager",
    "head_of_ops",
    "founder_owner",
    "agency_operator",
    "unknown",
}
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}
RETRY_BACKOFF_SECONDS = (0.5, 1.0)
PRIMARY_SCHEMA_VERSION = "primary_v2"
LEGACY_SCHEMA_VERSION = "legacy_v2"
DEEP_DIVE_SCHEMA_VERSION = "deep_dive_v1"
CLUSTER_SCHEMA_VERSION = "cluster_v1"
GTM_SCHEMA_VERSION = "gtm_v1"
MAX_LLM_RESPONSE_BYTES = 5_000_000


PRIMARY_PROMPT_TEMPLATE = """You are a B2B SaaS product manager analyzing Reddit pain signals.

Task:
1. Determine if this pain is monetizable for a business software product.
2. Score pain intensity and willingness to pay.
3. Categorize the niche.
4. Extract competitor software names mentioned negatively.
5. Classify the post type before monetization scoring.
6. Identify first-handness and buyer authority.
7. Return 1-3 short evidence spans copied from the post text.
8. Keep compatibility fields (category, severity).

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
  "severity": "low",
  "post_type": "first_person_pain",
  "first_handness": "first_hand",
  "buyer_authority": "founder_owner",
  "evidence_spans": ["copied evidence"]
}

Rules:
- pain_level: integer 0..10
- willingness_to_pay: integer 0..10
- competitor_tags: array of lowercase software tags, empty array if none
- post_type: one of first_person_pain, solution_request, founder_pitch, news_analysis, tool_comparison, advice_thread, vendor_rant
- first_handness: one of first_hand, second_hand, aggregated, speculative, unknown
- buyer_authority: one of intern, ic, engineer, manager, head_of_ops, founder_owner, agency_operator, unknown
- evidence_spans: array with 1..3 short quotes copied from the post, max 160 chars each

Title: {title}
Body: {body}
"""

LEGACY_PROMPT_TEMPLATE = """Analyze this post and extract pain point JSON:
{
  "category": "complaint",
  "summary": "one sentence summary",
  "severity": "low",
  "post_type": "advice_thread",
  "first_handness": "unknown",
  "buyer_authority": "unknown",
  "evidence_spans": ["copied evidence"]
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
    prompt_hash: str | None = None
    fallback_reason: str | None = None
    schema_version: str | None = None
    provider: str | None = None
    request_path: str | None = None
    candidate_stage: str | None = None


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
    post_type: str = "advice_thread"
    first_handness: str = "unknown"
    buyer_authority: str = "unknown"
    evidence_spans: list[str] = field(default_factory=list)
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
    DEFAULT_BASE_URLS = {
        "openrouter": "https://openrouter.ai/api/v1/chat/completions",
        "codex": "https://api.openai.com/v1/chat/completions",
        "openai": "https://api.openai.com/v1/chat/completions",
        "openai-codex": "https://chatgpt.com/backend-api/codex",
    }

    def __init__(
        self,
        api_key: str,
        model: str,
        deep_dive_model: str | None = None,
        cluster_model: str | None = None,
        gtm_model: str | None = None,
        pricing_map: dict[str, dict[str, float]] | None = None,
        budget_guard: "BudgetGuard | None" = None,
        cache_db: Any | None = None,
        provider: str = "openrouter",
        api_base: str = "",
        reasoning_effort: str = "",
        temperature: float | None = None,
        max_tokens: int | None = None,
        primary_max_output_tokens: int | None = None,
        max_response_bytes: int = MAX_LLM_RESPONSE_BYTES,
        app_url: str = "https://github.com/max-chad/pain_finder",
        app_name: str = "pain_finder",
    ):
        self.api_key = api_key
        self.model = model
        self.deep_dive_model = deep_dive_model or model
        self.cluster_model = cluster_model or model
        self.gtm_model = gtm_model or model
        self.pricing_map = pricing_map or {}
        self.budget_guard = budget_guard
        self.cache_db = cache_db
        self.provider = provider.strip().lower() or "openrouter"
        self.api_base = api_base.strip()
        self.reasoning_effort = reasoning_effort.strip().lower()
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.primary_max_output_tokens = primary_max_output_tokens
        self.max_response_bytes = max(1, max_response_bytes)
        self.app_url = app_url
        self.app_name = app_name
        self.base_url = self._resolve_base_url()

    def _resolve_base_url(self) -> str:
        if self.api_base:
            api_base = self.api_base.rstrip("/")
            if self.provider == "openai-codex":
                return api_base.removesuffix("/responses")
            if api_base.endswith("/chat/completions"):
                return api_base
            return f"{api_base}/chat/completions"
        return self.DEFAULT_BASE_URLS.get(self.provider, self.DEFAULT_BASE_URLS["openai"])

    def _uses_openai_codex_backend(self) -> bool:
        return self.provider == "openai-codex" or "chatgpt.com/backend-api/codex" in self.base_url.lower()

    def _is_openai_compatible(self) -> bool:
        return self.provider in {"openai", "codex", "openrouter", "openai-codex"}

    @staticmethod
    def _build_codex_headers(access_token: str) -> dict[str, str]:
        headers = {
            "User-Agent": "codex_cli_rs/0.0.0 (pain_finder)",
            "originator": "codex_cli_rs",
        }
        try:
            if not isinstance(access_token, str) or not access_token.strip():
                raise ValueError("missing access token")
            parts = access_token.split(".")
            if len(parts) < 2:
                raise ValueError("missing JWT payload")
            payload_b64 = parts[1] + "=" * (-len(parts[1]) % 4)
            claims = json.loads(base64.urlsafe_b64decode(payload_b64))
            auth_claims = claims.get("https://api.openai.com/auth", {}) if isinstance(claims, dict) else {}
            account_id = auth_claims.get("chatgpt_account_id") if isinstance(auth_claims, dict) else None
            if not isinstance(account_id, str) or not account_id.strip():
                raise ValueError("missing ChatGPT-Account-ID claim")
            headers["ChatGPT-Account-ID"] = account_id.strip()
        except Exception as e:
            raise ValueError("openai-codex routing requires a valid ChatGPT-Account-ID claim") from e
        return headers

    def _build_headers(self) -> dict[str, str]:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        if self.provider == "openrouter":
            headers.update({"HTTP-Referer": self.app_url, "X-Title": self.app_name})
        if self._uses_openai_codex_backend():
            headers.update(self._build_codex_headers(self.api_key))
        return headers

    def _build_request_body(self, *, model: str, prompt: str, max_output_tokens: int | None = None) -> dict[str, Any]:
        request_body: dict[str, Any] = {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "response_format": {"type": "json_object"},
        }
        if self.temperature is not None:
            request_body["temperature"] = self.temperature
        token_limit = max_output_tokens if max_output_tokens is not None else self.max_tokens
        if token_limit is not None:
            if self.provider in {"openai", "codex"} and (model.startswith("gpt-5") or model.startswith("o")):
                request_body["max_completion_tokens"] = token_limit
            else:
                request_body["max_tokens"] = token_limit
        if self.reasoning_effort and self._is_openai_compatible():
            request_body["reasoning_effort"] = self.reasoning_effort
        return request_body

    async def _post_json_with_response_limit(
        self,
        *,
        client: httpx.AsyncClient,
        url: str,
        payload: dict[str, Any],
        headers: dict[str, str],
    ) -> dict[str, Any]:
        async with client.stream("POST", url, json=payload, headers=headers) as response:
            body = bytearray()
            async for chunk in response.aiter_bytes():
                body.extend(chunk)
                if len(body) > self.max_response_bytes:
                    raise RuntimeError(f"LLM response exceeded {self.max_response_bytes} bytes")
            bounded_response = httpx.Response(
                response.status_code,
                headers=response.headers,
                content=bytes(body),
                request=response.request,
                extensions=response.extensions,
            )
        bounded_response.raise_for_status()
        return json.loads(bounded_response.content.decode(bounded_response.encoding or "utf-8", errors="replace"))

    def _ensure_responses_text_within_limit(self, text: str) -> None:
        if len(text.encode("utf-8")) > self.max_response_bytes:
            raise RuntimeError(f"OpenAI Responses text exceeded {self.max_response_bytes} bytes")

    def _extract_responses_text(self, final_response: Any, streamed_parts: list[str]) -> str:
        text = "".join(part for part in streamed_parts if part).strip()
        if text:
            self._ensure_responses_text_within_limit(text)
            return text
        direct = getattr(final_response, "output_text", "")
        if isinstance(direct, str) and direct.strip():
            stripped = direct.strip()
            self._ensure_responses_text_within_limit(stripped)
            return stripped
        for item in getattr(final_response, "output", []) or []:
            for content in getattr(item, "content", []) or []:
                maybe_text = getattr(content, "text", "")
                if isinstance(maybe_text, str) and maybe_text.strip():
                    stripped = maybe_text.strip()
                    self._ensure_responses_text_within_limit(stripped)
                    return stripped
        return ""

    @staticmethod
    def _responses_usage_to_dict(usage: Any) -> dict[str, int] | None:
        if usage is None:
            return None
        prompt_tokens = OpenRouterClient._usage_token_count(getattr(usage, "input_tokens", 0))
        completion_tokens = OpenRouterClient._usage_token_count(getattr(usage, "output_tokens", 0))
        return {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
        }

    @staticmethod
    def _usage_token_count(value: Any) -> int:
        try:
            parsed = int(value or 0)
        except (OverflowError, TypeError, ValueError):
            return 0
        return max(0, parsed)

    async def _request_codex_responses_payload(
        self,
        *,
        prompt: str,
        model: str,
        max_output_tokens: int | None = None,
    ) -> tuple[dict[str, Any] | None, dict[str, int] | None]:
        def _run() -> tuple[dict[str, Any] | None, dict[str, int] | None]:
            client = OpenAI(
                api_key=self.api_key,
                base_url=self.base_url,
                default_headers=self._build_codex_headers(self.api_key),
            )
            streamed_parts: list[str] = []
            stream_kwargs: dict[str, Any] = {
                "model": model,
                "instructions": "Return only the JSON object requested by the user task.",
                "input": [
                    {
                        "role": "user",
                        "content": [{"type": "input_text", "text": prompt}],
                    }
                ],
                "store": False,
            }
            token_limit = max_output_tokens if max_output_tokens is not None else self.max_tokens
            if token_limit is not None:
                stream_kwargs["max_output_tokens"] = token_limit
            if self.reasoning_effort:
                stream_kwargs["reasoning"] = {"effort": self.reasoning_effort, "summary": "auto"}
            streamed_bytes = 0
            with client.responses.stream(**stream_kwargs) as stream:
                for event in stream:
                    event_type = getattr(event, "type", "")
                    if event_type in {"response.output_text.delta", "output_text.delta"}:
                        delta = getattr(event, "delta", "")
                        if delta:
                            streamed_bytes += len(delta.encode("utf-8"))
                            if streamed_bytes > self.max_response_bytes:
                                raise RuntimeError(f"OpenAI Responses stream exceeded {self.max_response_bytes} bytes")
                            streamed_parts.append(delta)
                final_response = stream.get_final_response()
            raw_text = self._extract_responses_text(final_response, streamed_parts)
            if not raw_text:
                return None, self._responses_usage_to_dict(getattr(final_response, "usage", None))
            payload = self._safe_json_load(raw_text)
            usage = self._responses_usage_to_dict(getattr(final_response, "usage", None))
            return payload, usage

        return await asyncio.to_thread(_run)

    async def _record_usage_from_usage_dict(
        self,
        *,
        usage: dict[str, int] | None,
        model: str,
        operation: str,
        post_id: str | None,
        prompt_hash: str,
        fallback_reason: str | None,
        schema_version: str,
        candidate_stage: str,
    ) -> None:
        if not usage:
            return
        prompt_tokens = self._usage_token_count(usage.get("prompt_tokens", 0))
        completion_tokens = self._usage_token_count(usage.get("completion_tokens", 0))
        cost_usd = self._estimate_cost_usd(model, prompt_tokens, completion_tokens)

        if self.budget_guard is not None:
            try:
                await self.budget_guard.record_usage(
                    model=model,
                    operation=operation,
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    cost_usd=cost_usd,
                    post_id=post_id,
                    prompt_hash=prompt_hash,
                    fallback_reason=fallback_reason,
                    schema_version=schema_version,
                    provider=self.provider,
                    request_path=self._request_path(),
                    candidate_stage=candidate_stage,
                )
            except Exception as e:
                logger.warning(
                    "llm_usage_record_failed model=%s operation=%s post_id=%s error=%s",
                    model,
                    operation,
                    post_id,
                    e,
                )
                raise OpenRouterUsageAccountingError(
                    f"llm_usage_record_failed model={model} operation={operation} post_id={post_id}"
                ) from e

    def set_budget_guard(self, budget_guard: "BudgetGuard | None") -> None:
        self.budget_guard = budget_guard

    async def analyze_post(self, title: str, body: str, post_id: str | None = None) -> AnalysisResult | None:
        prompt = PRIMARY_PROMPT_TEMPLATE.replace("{title}", title).replace("{body}", body[:5000])
        payload = await self._request_json_response(
            prompt=prompt,
            model=self.model,
            operation="classify_primary",
            post_id=post_id,
            validate_payload=self._is_valid_primary_payload,
            schema_version=PRIMARY_SCHEMA_VERSION,
            candidate_stage="primary",
            max_output_tokens=self.primary_max_output_tokens,
        )
        if payload is None:
            return None
        result = self._parse_primary_result(payload)
        if result is None:
            logger.warning("OpenRouter primary output failed validation: %s", payload)
        return result

    async def analyze_legacy_post(
        self,
        title: str,
        body: str,
        post_id: str | None = None,
        fallback_reason: str | None = None,
    ) -> AnalysisResult | None:
        prompt = LEGACY_PROMPT_TEMPLATE.replace("{title}", title).replace("{body}", body[:4000])
        payload = await self._request_json_response(
            prompt=prompt,
            model=self.model,
            operation="classify_legacy",
            post_id=post_id,
            validate_payload=self._is_valid_legacy_payload,
            schema_version=LEGACY_SCHEMA_VERSION,
            fallback_reason=fallback_reason,
            candidate_stage="primary_fallback",
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
            validate_payload=self._is_valid_deep_dive_payload,
            schema_version=DEEP_DIVE_SCHEMA_VERSION,
            candidate_stage="deep_dive",
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
            validate_payload=self._is_valid_cluster_label_payload,
            schema_version=CLUSTER_SCHEMA_VERSION,
            candidate_stage="cluster",
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
            validate_payload=self._is_valid_gtm_payload,
            schema_version=GTM_SCHEMA_VERSION,
            candidate_stage="gtm",
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
        validate_payload: Callable[[dict[str, Any]], bool] | None = None,
        schema_version: str,
        candidate_stage: str,
        fallback_reason: str | None = None,
        max_output_tokens: int | None = None,
    ) -> dict[str, Any] | None:
        token_limit = max_output_tokens if max_output_tokens is not None else self.max_tokens
        cache_key = self._build_cache_key(
            model=model,
            operation=operation,
            prompt=prompt,
            provider=self.provider,
            request_path=self._request_path(),
            reasoning_effort=self.reasoning_effort,
            temperature=self.temperature,
            token_limit=token_limit,
        )
        prompt_hash = self._prompt_hash(prompt)
        cached_payload = await self._get_cached_payload(cache_key)
        if cached_payload is not None:
            if validate_payload is not None and not validate_payload(cached_payload):
                logger.warning(
                    "openrouter_cache_invalid model=%s operation=%s key=%s",
                    model,
                    operation,
                    cache_key,
                )
            else:
                logger.info("openrouter_cache_hit model=%s operation=%s", model, operation)
                return cached_payload

        async with await self._admit_budget(operation):
            if self._uses_openai_codex_backend():
                try:
                    payload, usage = await self._request_codex_responses_payload(
                        prompt=prompt,
                        model=model,
                        max_output_tokens=max_output_tokens,
                    )
                except Exception as e:
                    logger.warning("OpenAI Codex request failed: %s", e)
                    return None
                await self._record_usage_from_usage_dict(
                    usage=usage,
                    model=model,
                    operation=operation,
                    post_id=post_id,
                    prompt_hash=prompt_hash,
                    fallback_reason=fallback_reason,
                    schema_version=schema_version,
                    candidate_stage=candidate_stage,
                )
                if payload is None:
                    return None
                is_valid_payload = validate_payload(payload) if validate_payload is not None else True
                if is_valid_payload:
                    await self._set_cached_payload(cache_key=cache_key, model=model, operation=operation, payload=payload)
                else:
                    logger.warning(
                        "openrouter_cache_skip_invalid_payload model=%s operation=%s key=%s",
                        model,
                        operation,
                        cache_key,
                    )
                return payload

            headers = self._build_headers()
            request_body = self._build_request_body(model=model, prompt=prompt, max_output_tokens=max_output_tokens)

            _max_attempts = len(RETRY_BACKOFF_SECONDS)
            try:
                async with httpx.AsyncClient(timeout=45) as client:
                    for attempt in range(1, _max_attempts + 1):
                        try:
                            response_json = await self._post_json_with_response_limit(
                                client=client,
                                url=self.base_url,
                                payload=request_body,
                                headers=headers,
                            )
                            await self._record_usage_from_response(
                                response_json=response_json,
                                model=model,
                                operation=operation,
                                post_id=post_id,
                                prompt_hash=prompt_hash,
                                fallback_reason=fallback_reason,
                                schema_version=schema_version,
                                candidate_stage=candidate_stage,
                            )
                            content = response_json["choices"][0]["message"]["content"]
                            payload = self._safe_json_load(content)
                            is_valid_payload = validate_payload(payload) if validate_payload is not None else True
                            if is_valid_payload:
                                await self._set_cached_payload(cache_key=cache_key, model=model, operation=operation, payload=payload)
                            else:
                                logger.warning(
                                    "openrouter_cache_skip_invalid_payload model=%s operation=%s key=%s",
                                    model,
                                    operation,
                                    cache_key,
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
            except (httpx.HTTPError, KeyError, IndexError, TypeError, AttributeError, RuntimeError, json.JSONDecodeError) as e:
                logger.warning("OpenRouter request failed: %s", e)
                return None

    async def _admit_budget(self, operation: str) -> Any:
        if self.budget_guard is None:
            return _NullBudgetAdmission()
        admit = getattr(self.budget_guard, "admit", None)
        if callable(admit) and hasattr(type(self.budget_guard), "admit"):
            return await admit(operation)
        await self.budget_guard.ensure_can_spend(operation)
        return _NullBudgetAdmission()

    @staticmethod
    def _prompt_hash(prompt: str) -> str:
        return hashlib.sha256(prompt.encode("utf-8")).hexdigest()

    def _request_path(self) -> str:
        if self._uses_openai_codex_backend():
            return f"{self.base_url.rstrip('/')}/responses"
        return self.base_url

    @classmethod
    def _build_cache_key(
        cls,
        *,
        model: str,
        operation: str,
        prompt: str,
        provider: str,
        request_path: str,
        reasoning_effort: str,
        temperature: float | None,
        token_limit: int | None,
    ) -> str:
        digest = cls._prompt_hash(prompt)
        config_fingerprint = hashlib.sha256(
            json.dumps(
                {
                    "provider": provider,
                    "request_path": request_path,
                    "reasoning_effort": reasoning_effort,
                    "temperature": temperature,
                    "token_limit": token_limit,
                },
                sort_keys=True,
            ).encode("utf-8")
        ).hexdigest()[:16]
        return f"{operation}:{model}:{config_fingerprint}:{digest}"

    async def _get_cached_payload(self, cache_key: str) -> dict[str, Any] | None:
        if self.cache_db is None:
            return None
        get_fn = getattr(self.cache_db, "get_cached_llm_payload", None)
        if get_fn is None:
            return None
        try:
            return await get_fn(cache_key)
        except Exception as e:
            logger.warning("OpenRouter cache lookup failed for key=%s: %s", cache_key, e)
            return None

    async def _set_cached_payload(
        self,
        *,
        cache_key: str,
        model: str,
        operation: str,
        payload: dict[str, Any],
    ) -> None:
        if self.cache_db is None:
            return
        set_fn = getattr(self.cache_db, "set_cached_llm_payload", None)
        if set_fn is None:
            return
        try:
            await set_fn(cache_key=cache_key, model=model, operation=operation, payload=payload)
        except Exception as e:
            logger.warning("OpenRouter cache write failed for key=%s: %s", cache_key, e)

    async def _record_usage_from_response(
        self,
        *,
        response_json: dict[str, Any],
        model: str,
        operation: str,
        post_id: str | None,
        prompt_hash: str,
        fallback_reason: str | None,
        schema_version: str,
        candidate_stage: str,
    ) -> None:
        usage = response_json.get("usage")
        if not isinstance(usage, dict):
            return

        prompt_tokens = self._usage_token_count(usage.get("prompt_tokens", 0))
        completion_tokens = self._usage_token_count(usage.get("completion_tokens", 0))
        cost_usd = self._estimate_cost_usd(model, prompt_tokens, completion_tokens)

        if self.budget_guard is not None:
            try:
                await self.budget_guard.record_usage(
                    model=model,
                    operation=operation,
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    cost_usd=cost_usd,
                    post_id=post_id,
                    prompt_hash=prompt_hash,
                    fallback_reason=fallback_reason,
                    schema_version=schema_version,
                    provider=self.provider,
                    request_path=self._request_path(),
                    candidate_stage=candidate_stage,
                )
            except Exception as e:
                logger.warning(
                    "llm_usage_record_failed model=%s operation=%s post_id=%s error=%s",
                    model,
                    operation,
                    post_id,
                    e,
                )
                raise OpenRouterUsageAccountingError(
                    f"llm_usage_record_failed model={model} operation={operation} post_id={post_id}"
                ) from e

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

    def _is_valid_primary_payload(self, payload: dict[str, Any]) -> bool:
        return self._parse_primary_result(payload) is not None

    def _is_valid_legacy_payload(self, payload: dict[str, Any]) -> bool:
        return self._parse_legacy_result(payload) is not None

    def _is_valid_deep_dive_payload(self, payload: dict[str, Any]) -> bool:
        return self._parse_deep_dive_result(payload) is not None

    def _is_valid_cluster_label_payload(self, payload: dict[str, Any]) -> bool:
        return self._parse_cluster_label(payload) is not None

    def _is_valid_gtm_payload(self, payload: dict[str, Any]) -> bool:
        return self._parse_gtm_result(payload) is not None

    @staticmethod
    def _default_post_type_for_category(category: str) -> str:
        if category == "complaint":
            return "first_person_pain"
        if category == "unsolved":
            return "solution_request"
        return "advice_thread"

    def _parse_primary_result(self, payload: dict[str, Any]) -> AnalysisResult | None:
        category = payload.get("category")
        severity = payload.get("severity")
        summary = payload.get("summary")
        monetizable = payload.get("is_monetizable")
        pain_level = payload.get("pain_level")
        willingness_to_pay = payload.get("willingness_to_pay")
        niche_category = payload.get("niche_category")
        competitor_tags = payload.get("competitor_tags", [])
        post_type = payload.get("post_type", self._default_post_type_for_category(str(category)))
        first_handness = payload.get("first_handness", "unknown")
        buyer_authority = payload.get("buyer_authority", "unknown")
        evidence_spans = payload.get("evidence_spans", [])

        if category not in VALID_CATEGORIES:
            return None
        if severity not in VALID_SEVERITIES:
            return None
        if not isinstance(summary, str) or not summary.strip():
            return None
        if not isinstance(monetizable, bool):
            return None
        if isinstance(pain_level, bool) or not isinstance(pain_level, int) or not (0 <= pain_level <= 10):
            return None
        if isinstance(willingness_to_pay, bool) or not isinstance(willingness_to_pay, int) or not (0 <= willingness_to_pay <= 10):
            return None
        if not isinstance(niche_category, str):
            return None
        if not isinstance(competitor_tags, list) or any(not isinstance(item, str) for item in competitor_tags):
            return None
        if post_type not in VALID_POST_TYPES:
            return None
        if first_handness not in VALID_FIRST_HANDNESS:
            return None
        if buyer_authority not in VALID_BUYER_AUTHORITIES:
            return None
        if not isinstance(evidence_spans, list) or any(not isinstance(item, str) for item in evidence_spans):
            return None
        cleaned_evidence = [item.strip()[:160] for item in evidence_spans if item.strip()][:3]

        return AnalysisResult(
            category=category,
            summary=summary.strip(),
            severity=severity,
            is_monetizable=monetizable,
            pain_level=pain_level,
            willingness_to_pay=willingness_to_pay if monetizable else min(willingness_to_pay, 3),
            niche_category=niche_category.strip(),
            competitor_tags=[item.strip().lower() for item in competitor_tags if item.strip()],
            post_type=post_type,
            first_handness=first_handness,
            buyer_authority=buyer_authority,
            evidence_spans=cleaned_evidence,
            raw_payload=payload,
        )

    def _parse_legacy_result(self, payload: dict[str, Any]) -> AnalysisResult | None:
        category = payload.get("category")
        severity = payload.get("severity")
        summary = payload.get("summary")
        competitor_tags = payload.get("competitor_tags", [])
        post_type = payload.get("post_type", self._default_post_type_for_category(str(category)))
        first_handness = payload.get("first_handness", "unknown")
        buyer_authority = payload.get("buyer_authority", "unknown")
        evidence_spans = payload.get("evidence_spans", [])

        if category not in VALID_CATEGORIES:
            return None
        if severity not in VALID_SEVERITIES:
            return None
        if not isinstance(summary, str) or not summary.strip():
            return None
        if not isinstance(competitor_tags, list) or any(not isinstance(item, str) for item in competitor_tags):
            competitor_tags = []
        if post_type not in VALID_POST_TYPES:
            return None
        if first_handness not in VALID_FIRST_HANDNESS:
            return None
        if buyer_authority not in VALID_BUYER_AUTHORITIES:
            return None
        if not isinstance(evidence_spans, list) or any(not isinstance(item, str) for item in evidence_spans):
            evidence_spans = []

        return AnalysisResult(
            category=category,
            summary=summary.strip(),
            severity=severity,
            competitor_tags=[item.strip().lower() for item in competitor_tags if isinstance(item, str) and item.strip()],
            post_type=post_type,
            first_handness=first_handness,
            buyer_authority=buyer_authority,
            evidence_spans=[item.strip()[:160] for item in evidence_spans if isinstance(item, str) and item.strip()][:3],
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
