from unittest.mock import AsyncMock

from types import SimpleNamespace

import json
import httpx
import pytest
import respx

from openrouter import AnalysisResult, DeepDiveResult, OpenRouterClient


async def test_analyze_returns_primary_b2b_result(respx_mock):
    respx_mock.post("https://openrouter.ai/api/v1/chat/completions").mock(
        return_value=httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": (
                                '{"is_monetizable": true, "pain_level": 8, "willingness_to_pay": 9, '
                                '"niche_category": "E-commerce", "competitor_tags": ["shopify"], '
                                '"summary": "Inventory sync is failing for stores", "category": "complaint", '
                                '"severity": "high", "post_type": "first_person_pain", '
                                '"first_handness": "first_hand", "buyer_authority": "founder_owner", '
                                '"evidence_spans": ["stock sync lags", "we lose sales"]}'
                            )
                        }
                    }
                ]
            },
        )
    )

    client = OpenRouterClient(api_key="test-key", model="test-model")
    result = await client.analyze_post(
        title="Shopify inventory mismatch",
        body="We lose sales when stock sync lags",
    )

    assert result is not None
    assert result.is_monetizable is True
    assert result.willingness_to_pay == 9
    assert result.niche_category == "E-commerce"
    assert result.competitor_tags == ["shopify"]
    assert result.post_type == "first_person_pain"
    assert result.first_handness == "first_hand"
    assert result.buyer_authority == "founder_owner"
    assert result.evidence_spans == ["stock sync lags", "we lose sales"]


async def test_analyze_rejects_invalid_primary_schema(respx_mock):
    respx_mock.post("https://openrouter.ai/api/v1/chat/completions").mock(
        return_value=httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": (
                                '{"is_monetizable": "yes", "pain_level": 11, '
                                '"willingness_to_pay": 9, "niche_category": "X", '
                                '"summary": "bad", "category": "complaint", "severity": "high", '
                                '"post_type": "mystery", "first_handness": "first_hand", '
                                '"buyer_authority": "founder_owner", "evidence_spans": []}'
                            )
                        }
                    }
                ]
            },
        )
    )

    client = OpenRouterClient(api_key="test-key", model="test-model")
    result = await client.analyze_post(title="T", body="B")
    assert result is None


async def test_legacy_analysis_returns_result(respx_mock):
    respx_mock.post("https://openrouter.ai/api/v1/chat/completions").mock(
        return_value=httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": '{"category": "wish", "summary": "Need export feature", "severity": "low"}'
                        }
                    }
                ]
            },
        )
    )

    client = OpenRouterClient(api_key="test-key", model="test-model")
    result = await client.analyze_legacy_post(title="Wish", body="Need CSV")
    assert isinstance(result, AnalysisResult)
    assert result.category == "wish"


async def test_deep_dive_analysis_returns_structured_result(respx_mock):
    respx_mock.post("https://openrouter.ai/api/v1/chat/completions").mock(
        return_value=httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": '{"workarounds": ["manual CSV"], "competitors": ["Tool A"], "feature_wishlist": ["auto sync"], "buying_signals": ["paying now"], "icp_hypothesis": "SMB stores", "actionable_summary": "Build auto inventory sync"}'
                        }
                    }
                ]
            },
        )
    )

    client = OpenRouterClient(api_key="test-key", model="test-model", deep_dive_model="deep-model")
    result = await client.analyze_deep_dive(title="T", thread_text="Thread")
    assert isinstance(result, DeepDiveResult)
    assert result.actionable_summary.startswith("Build")


async def test_analyze_handles_malformed_json(respx_mock):
    respx_mock.post("https://openrouter.ai/api/v1/chat/completions").mock(
        return_value=httpx.Response(
            200,
            json={"choices": [{"message": {"content": "not valid json"}}]},
        )
    )

    client = OpenRouterClient(api_key="test-key", model="test-model")
    result = await client.analyze_post(title="Test", body="Test body")
    assert result is None


@pytest.mark.parametrize(
    "payload",
    [
        [],
        {"choices": None},
        {"choices": [{"message": {"content": None}}]},
    ],
)
async def test_analyze_handles_malformed_provider_payload_shape(respx_mock, payload):
    respx_mock.post("https://openrouter.ai/api/v1/chat/completions").mock(
        return_value=httpx.Response(200, json=payload)
    )

    client = OpenRouterClient(api_key="test-key", model="test-model")
    result = await client.analyze_post(title="Test", body="Test body")

    assert result is None


async def test_analyze_handles_api_error(respx_mock):
    respx_mock.post("https://openrouter.ai/api/v1/chat/completions").mock(
        return_value=httpx.Response(500)
    )
    client = OpenRouterClient(api_key="test-key", model="test-model")
    result = await client.analyze_post(title="Test", body="Test body")
    assert result is None


async def test_body_truncated_for_large_prompt(respx_mock):
    long_body = "A" * 7000 + "OVERFLOW_MARKER"
    captured_requests = []

    def capture(request):
        captured_requests.append(request)
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": '{"is_monetizable": false, "pain_level": 0, "willingness_to_pay": 0, "niche_category": "", "competitor_tags": [], "summary": "s", "category": "complaint", "severity": "low"}'
                        }
                    }
                ]
            },
        )

    respx_mock.post("https://openrouter.ai/api/v1/chat/completions").mock(side_effect=capture)
    client = OpenRouterClient(api_key="test-key", model="test-model")
    await client.analyze_post(title="Test", body=long_body)

    import json

    req_body = json.loads(captured_requests[0].content)
    prompt = req_body["messages"][0]["content"]
    assert "OVERFLOW_MARKER" not in prompt


async def test_analyze_post_uses_primary_max_output_tokens(respx_mock):
    captured_requests = []

    def capture(request):
        captured_requests.append(request)
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": '{"is_monetizable": true, "pain_level": 6, "willingness_to_pay": 7, "niche_category": "Ops", "competitor_tags": [], "summary": "Manual process", "category": "complaint", "severity": "medium"}'
                        }
                    }
                ]
            },
        )

    respx_mock.post("https://api.openai.com/v1/chat/completions").mock(side_effect=capture)
    client = OpenRouterClient(
        api_key="test-key",
        model="gpt-5.3-spark",
        provider="codex",
        max_tokens=4096,
        primary_max_output_tokens=321,
    )

    result = await client.analyze_post(title="Need automation", body="Manual process is painful")

    assert result is not None
    import json

    req_body = json.loads(captured_requests[0].content)
    assert req_body["max_completion_tokens"] == 321


async def test_openrouter_provider_uses_primary_max_output_tokens_in_request_body(respx_mock):
    captured_requests = []

    def capture(request):
        captured_requests.append(request)
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": '{"is_monetizable": true, "pain_level": 6, "willingness_to_pay": 7, "niche_category": "Ops", "competitor_tags": [], "summary": "Manual process", "category": "complaint", "severity": "medium"}'
                        }
                    }
                ]
            },
        )

    respx_mock.post("https://openrouter.ai/api/v1/chat/completions").mock(side_effect=capture)
    client = OpenRouterClient(
        api_key="test-key",
        model="gpt-5.3-spark",
        provider="openrouter",
        max_tokens=4096,
        primary_max_output_tokens=321,
    )

    result = await client.analyze_post(title="Need automation", body="Manual process is painful")

    assert result is not None
    import json

    req_body = json.loads(captured_requests[0].content)
    assert req_body["max_tokens"] == 321


def test_full_chat_completions_api_base_is_not_double_suffixed():
    client = OpenRouterClient(
        api_key="test-key",
        model="m1",
        provider="openrouter",
        api_base="https://gateway.example/v1/chat/completions",
    )

    assert client.base_url == "https://gateway.example/v1/chat/completions"
    assert client._request_path() == "https://gateway.example/v1/chat/completions"


def test_openai_codex_responses_api_base_is_normalized_to_backend_root():
    client = OpenRouterClient(
        api_key="test-key",
        model="gpt-5.3-codex-spark",
        provider="openai-codex",
        api_base="https://chatgpt.com/backend-api/codex/responses",
    )

    assert client.base_url == "https://chatgpt.com/backend-api/codex"
    assert client._request_path() == "https://chatgpt.com/backend-api/codex/responses"


async def test_codex_provider_uses_openai_compatible_endpoint_and_reasoning_effort(respx_mock):
    captured_requests = []

    def capture(request):
        captured_requests.append(request)
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": '{"is_monetizable": true, "pain_level": 7, "willingness_to_pay": 8, "niche_category": "Ops", "competitor_tags": [], "summary": "Works", "category": "complaint", "severity": "medium"}'
                        }
                    }
                ]
            },
        )

    respx_mock.post("https://api.openai.com/v1/chat/completions").mock(side_effect=capture)
    client = OpenRouterClient(
        api_key="test-key",
        model="gpt-5.3-spark",
        provider="codex",
        reasoning_effort="high",
    )

    result = await client.analyze_post(title="Need automation", body="Manual process is painful")

    assert result is not None
    assert len(captured_requests) == 1
    import json

    req_body = json.loads(captured_requests[0].content)
    assert req_body["reasoning_effort"] == "high"
    assert captured_requests[0].headers["Authorization"] == "Bearer test-key"


def test_codex_header_builder_extracts_account_id_from_jwt():
    import base64
    import json

    def _segment(payload: dict[str, object]) -> str:
        encoded = base64.urlsafe_b64encode(json.dumps(payload).encode("utf-8")).decode("utf-8")
        return encoded.rstrip("=")

    token = ".".join(
        [
            _segment({"alg": "none"}),
            _segment({"https://api.openai.com/auth": {"chatgpt_account_id": "acct-reserve-123"}}),
            "signature",
        ]
    )

    headers = OpenRouterClient._build_codex_headers(token)

    assert headers["originator"] == "codex_cli_rs"
    assert headers["User-Agent"].startswith("codex_cli_rs/")
    assert headers["ChatGPT-Account-ID"] == "acct-reserve-123"


async def test_openai_codex_provider_parses_streamed_json_and_tracks_usage(monkeypatch):
    from types import SimpleNamespace

    captured_kwargs = {}

    class FakeStream:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def __iter__(self):
            payload = (
                '{"is_monetizable": true, "pain_level": 7, "willingness_to_pay": 8, '
                '"niche_category": "Ops", "competitor_tags": [], '
                '"summary": "From stream", "category": "complaint", "severity": "medium"}'
            )
            yield SimpleNamespace(type="response.output_text.delta", delta=payload)

        def get_final_response(self):
            return SimpleNamespace(
                output=[],
                output_text="",
                usage=SimpleNamespace(input_tokens=120, output_tokens=45),
                status="completed",
            )

    class FakeResponses:
        def stream(self, **kwargs):
            captured_kwargs.update(kwargs)
            return FakeStream()

    class FakeClient:
        def __init__(self, *args, **kwargs):
            captured_kwargs["client_kwargs"] = kwargs
            self.responses = FakeResponses()

    monkeypatch.setattr("openrouter.OpenAI", FakeClient)

    budget = AsyncMock()
    token = "eyJhbGciOiAibm9uZSJ9.eyJodHRwczovL2FwaS5vcGVuYWkuY29tL2F1dGgiOiB7ImNoYXRncHRfYWNjb3VudF9pZCI6ICJhY2N0LXJlc2VydmUtMTIzIn19.signature"
    client = OpenRouterClient(
        api_key=token,
        model="gpt-5.3-codex-spark",
        provider="openai-codex",
        api_base="https://chatgpt.com/backend-api/codex",
        reasoning_effort="high",
        budget_guard=budget,
    )

    result = await client.analyze_post(title="Need automation", body="Manual process is painful", post_id="reddit:abc")

    assert result is not None
    assert result.summary == "From stream"
    assert captured_kwargs["instructions"]
    assert captured_kwargs["reasoning"]["effort"] == "high"
    client_headers = captured_kwargs["client_kwargs"]["default_headers"]
    assert client_headers["originator"] == "codex_cli_rs"
    assert client_headers["User-Agent"].startswith("codex_cli_rs/")
    assert client_headers["ChatGPT-Account-ID"] == "acct-reserve-123"
    budget.record_usage.assert_awaited_once()
    usage_kwargs = budget.record_usage.await_args.kwargs
    assert usage_kwargs["prompt_tokens"] == 120
    assert usage_kwargs["completion_tokens"] == 45


async def test_openai_codex_provider_tracks_usage_for_empty_output(monkeypatch):
    from types import SimpleNamespace

    class FakeStream:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def __iter__(self):
            return iter(())

        def get_final_response(self):
            return SimpleNamespace(
                output=[],
                output_text="",
                usage=SimpleNamespace(input_tokens=90, output_tokens=12),
                status="completed",
            )

    class FakeResponses:
        def stream(self, **kwargs):
            return FakeStream()

    class FakeClient:
        def __init__(self, *args, **kwargs):
            self.responses = FakeResponses()

    monkeypatch.setattr("openrouter.OpenAI", FakeClient)

    budget = AsyncMock()
    client = OpenRouterClient(
        api_key="test-key",
        model="gpt-5.3-codex-spark",
        provider="openai-codex",
        api_base="https://chatgpt.com/backend-api/codex",
        budget_guard=budget,
    )

    result = await client.analyze_post(title="Need automation", body="Manual process is painful", post_id="reddit:empty")

    assert result is None
    budget.record_usage.assert_awaited_once()
    usage_kwargs = budget.record_usage.await_args.kwargs
    assert usage_kwargs["prompt_tokens"] == 90
    assert usage_kwargs["completion_tokens"] == 12
    assert usage_kwargs["post_id"] == "reddit:empty"


async def test_openai_codex_provider_rejects_oversized_streamed_response(monkeypatch):
    from types import SimpleNamespace

    class FakeStream:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def __iter__(self):
            yield SimpleNamespace(type="response.output_text.delta", delta="x" * 17)

        def get_final_response(self):
            return SimpleNamespace(output=[], output_text="", usage=None, status="completed")

    class FakeResponses:
        def stream(self, **kwargs):
            return FakeStream()

    class FakeClient:
        def __init__(self, *args, **kwargs):
            self.responses = FakeResponses()

    monkeypatch.setattr("openrouter.OpenAI", FakeClient)

    client = OpenRouterClient(
        api_key="test-key",
        model="gpt-5.3-codex-spark",
        provider="openai-codex",
        api_base="https://chatgpt.com/backend-api/codex",
        max_response_bytes=16,
    )

    result = await client.analyze_post(title="Need automation", body="Manual process is painful")

    assert result is None


async def test_analyze_retries_transient_http_errors(respx_mock):
    from unittest.mock import AsyncMock, patch

    route = respx_mock.post("https://openrouter.ai/api/v1/chat/completions").mock(
        side_effect=[
            httpx.Response(503),
            httpx.Response(
                200,
                json={
                    "choices": [
                        {
                            "message": {
                                "content": '{"is_monetizable": true, "pain_level": 6, "willingness_to_pay": 7, "niche_category": "DevOps", "summary": "Retry worked", "category": "complaint", "severity": "medium"}'
                            }
                        }
                    ]
                },
            ),
        ]
    )
    client = OpenRouterClient(api_key="test-key", model="test-model")

    with patch("openrouter.asyncio.sleep", new=AsyncMock()) as sleep_mock:
        result = await client.analyze_post(title="Test", body="Body")

    assert result is not None
    assert result.summary == "Retry worked"
    assert route.call_count == 2
    assert sleep_mock.await_count == 1


async def test_cluster_label_and_gtm_methods(respx_mock):
    route = respx_mock.post("https://openrouter.ai/api/v1/chat/completions").mock(
        side_effect=[
            httpx.Response(
                200,
                json={
                    "choices": [
                        {
                            "message": {
                                "content": '{"label":"QuickBooks API Failures","summary":"Many SMB teams report failed ledger sync.","estimated_monetization_signal":"high","key_complaints":["sync","mapping"]}'
                            }
                        }
                    ]
                },
            ),
            httpx.Response(
                200,
                json={
                    "choices": [
                        {
                            "message": {
                                "content": (
                                    '{"name_options":["SyncPilot","LedgerFlow","ReconMate"],'
                                    '"hero_h1":"Stop failed accounting sync","hero_h2":"Recover hours every week",'
                                    '"mvp_features":["Retry queue","Diff checks","Alert routing"],'
                                    '"pricing_tier":"$49/mo",'
                                    '"positioning_rationale":"SMB finance teams need reliability first."}'
                                )
                            }
                        }
                    ]
                },
            ),
        ]
    )
    client = OpenRouterClient(
        api_key="test-key",
        model="m1",
        cluster_model="m2",
        gtm_model="m3",
    )
    label = await client.label_macro_cluster(cluster_text="sample", cluster_size=3)
    gtm = await client.generate_gtm(context="sample context", post_id="reddit:abc")

    assert label is not None
    assert label.label == "QuickBooks API Failures"
    assert gtm is not None
    assert gtm.name_options[0] == "SyncPilot"
    assert route.call_count == 2


async def test_openrouter_uses_cache_hit_without_http_call():
    cache_db = AsyncMock()
    cache_db.get_cached_llm_payload.return_value = {
        "is_monetizable": True,
        "pain_level": 7,
        "willingness_to_pay": 8,
        "niche_category": "DevOps",
        "competitor_tags": ["jira"],
        "summary": "Cached payload",
        "category": "complaint",
        "severity": "high",
    }

    budget = AsyncMock()
    client = OpenRouterClient(api_key="test-key", model="m1", budget_guard=budget, cache_db=cache_db)

    result = await client.analyze_post(title="Title", body="Body", post_id="reddit:cached")

    assert result is not None
    assert result.summary == "Cached payload"
    budget.ensure_can_spend.assert_not_called()
    cache_db.get_cached_llm_payload.assert_awaited_once()


def test_openrouter_cache_key_includes_generation_config():
    base_kwargs = {
        "model": "m1",
        "operation": "deep_dive",
        "prompt": "same prompt",
        "provider": "openrouter",
        "request_path": "https://openrouter.ai/api/v1/chat/completions",
        "reasoning_effort": "high",
    }

    baseline = OpenRouterClient._build_cache_key(**base_kwargs, temperature=0.1, token_limit=4000)
    hotter = OpenRouterClient._build_cache_key(**base_kwargs, temperature=0.7, token_limit=4000)
    shorter = OpenRouterClient._build_cache_key(**base_kwargs, temperature=0.1, token_limit=1000)

    assert baseline != hotter
    assert baseline != shorter


@respx.mock
async def test_openrouter_stores_successful_response_in_cache():
    respx.post("https://openrouter.ai/api/v1/chat/completions").mock(
        return_value=httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": '{"is_monetizable": true, "pain_level": 8, "willingness_to_pay": 8, "niche_category": "DevTools", "competitor_tags": [], "summary": "Need retry flow", "category": "complaint", "severity": "high"}'
                        }
                    }
                ]
            },
        )
    )

    cache_db = AsyncMock()
    cache_db.get_cached_llm_payload.return_value = None
    client = OpenRouterClient(api_key="test-key", model="m1", cache_db=cache_db)

    result = await client.analyze_post(title="Title", body="Body", post_id="reddit:abc")

    assert result is not None
    cache_db.set_cached_llm_payload.assert_awaited_once()
    kwargs = cache_db.set_cached_llm_payload.await_args.kwargs
    assert kwargs["model"] == "m1"
    assert kwargs["operation"] == "classify_primary"
    assert kwargs["payload"]["summary"] == "Need retry flow"


@respx.mock
async def test_openrouter_does_not_cache_invalid_primary_payload():
    route = respx.post("https://openrouter.ai/api/v1/chat/completions").mock(
        side_effect=[
            httpx.Response(
                200,
                json={
                    "choices": [
                        {
                            "message": {
                                "content": '{"is_monetizable": "yes", "pain_level": 11, "willingness_to_pay": 9, "niche_category": "X", "summary": "bad", "category": "complaint", "severity": "high"}'
                            }
                        }
                    ]
                },
            ),
            httpx.Response(
                200,
                json={
                    "choices": [
                        {
                            "message": {
                                "content": '{"is_monetizable": true, "pain_level": 8, "willingness_to_pay": 8, "niche_category": "DevTools", "competitor_tags": [], "summary": "valid", "category": "complaint", "severity": "high"}'
                            }
                        }
                    ]
                },
            ),
        ]
    )
    cache_db = AsyncMock()
    cache_db.get_cached_llm_payload.return_value = None
    client = OpenRouterClient(api_key="test-key", model="m1", cache_db=cache_db)

    first = await client.analyze_post(title="Title", body="Body", post_id="reddit:1")
    second = await client.analyze_post(title="Title", body="Body", post_id="reddit:1")

    assert first is None
    assert second is not None
    assert second.summary == "valid"
    assert route.call_count == 2
    cache_db.set_cached_llm_payload.assert_awaited_once()


@respx.mock
async def test_openrouter_bypasses_invalid_cached_payload():
    respx.post("https://openrouter.ai/api/v1/chat/completions").mock(
        return_value=httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": '{"is_monetizable": true, "pain_level": 8, "willingness_to_pay": 8, "niche_category": "DevTools", "competitor_tags": [], "summary": "from api", "category": "complaint", "severity": "high"}'
                        }
                    }
                ]
            },
        )
    )
    cache_db = AsyncMock()
    cache_db.get_cached_llm_payload.return_value = {
        "is_monetizable": "yes",
        "pain_level": 11,
        "willingness_to_pay": 9,
        "niche_category": "X",
        "summary": "bad",
        "category": "complaint",
        "severity": "high",
    }
    client = OpenRouterClient(api_key="test-key", model="m1", cache_db=cache_db)

    result = await client.analyze_post(title="Title", body="Body", post_id="reddit:1")

    assert result is not None
    assert result.summary == "from api"
    cache_db.set_cached_llm_payload.assert_awaited_once()


async def test_usage_tracking_calls_budget_guard(respx_mock):
    respx_mock.post("https://openrouter.ai/api/v1/chat/completions").mock(
        return_value=httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": '{"is_monetizable": true, "pain_level": 8, "willingness_to_pay": 8, "niche_category": "DevTools", "competitor_tags": [], "summary": "Need retry flow", "category": "complaint", "severity": "high"}'
                        }
                    }
                ],
                "usage": {"prompt_tokens": 1200, "completion_tokens": 300},
            },
        )
    )
    budget = AsyncMock()
    client = OpenRouterClient(
        api_key="test-key",
        model="m1",
        pricing_map={"m1": {"prompt_per_1k": 0.002, "completion_per_1k": 0.004}},
        budget_guard=budget,
    )

    result = await client.analyze_post(title="Title", body="Body", post_id="reddit:abc")

    assert result is not None
    budget.ensure_can_spend.assert_awaited_once_with("classify_primary")
    budget.record_usage.assert_awaited_once()
    call_kwargs = budget.record_usage.await_args.kwargs
    assert call_kwargs["model"] == "m1"
    assert call_kwargs["operation"] == "classify_primary"
    assert call_kwargs["prompt_tokens"] == 1200
    assert call_kwargs["completion_tokens"] == 300
    assert call_kwargs["cost_usd"] == 0.0036
    assert call_kwargs["schema_version"] == "primary_v2"
    assert call_kwargs["candidate_stage"] == "primary"
    assert call_kwargs["provider"] == "openrouter"
    assert call_kwargs["request_path"] == "https://openrouter.ai/api/v1/chat/completions"
    assert len(call_kwargs["prompt_hash"]) == 64


async def test_usage_tracking_tolerates_malformed_token_counts(respx_mock):
    respx_mock.post("https://openrouter.ai/api/v1/chat/completions").mock(
        return_value=httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": '{"is_monetizable": true, "pain_level": 8, "willingness_to_pay": 8, "niche_category": "DevTools", "competitor_tags": [], "summary": "Need retry flow", "category": "complaint", "severity": "high"}'
                        }
                    }
                ],
                "usage": {"prompt_tokens": "bad", "completion_tokens": -5},
            },
        )
    )
    budget = AsyncMock()
    client = OpenRouterClient(api_key="test-key", model="m1", budget_guard=budget)

    result = await client.analyze_post(title="Title", body="Body", post_id="reddit:abc")

    assert result is not None
    call_kwargs = budget.record_usage.await_args.kwargs
    assert call_kwargs["prompt_tokens"] == 0
    assert call_kwargs["completion_tokens"] == 0


async def test_usage_tracking_tolerates_overflow_token_counts(respx_mock):
    respx_mock.post("https://openrouter.ai/api/v1/chat/completions").mock(
        return_value=httpx.Response(
            200,
            content=json.dumps({
                "choices": [
                    {
                        "message": {
                            "content": '{"is_monetizable": true, "pain_level": 8, "willingness_to_pay": 8, "niche_category": "DevTools", "competitor_tags": [], "summary": "Need retry flow", "category": "complaint", "severity": "high"}'
                        }
                    }
                ],
                "usage": {"prompt_tokens": float("inf"), "completion_tokens": 50},
            }).encode("utf-8"),
            headers={"content-type": "application/json"},
        )
    )
    budget = AsyncMock()
    client = OpenRouterClient(api_key="test-key", model="m1", budget_guard=budget)

    result = await client.analyze_post(title="Title", body="Body", post_id="reddit:abc")

    assert result is not None
    call_kwargs = budget.record_usage.await_args.kwargs
    assert call_kwargs["prompt_tokens"] == 0
    assert call_kwargs["completion_tokens"] == 50


async def test_usage_tracking_records_usage_before_provider_payload_shape_failure(respx_mock):
    respx_mock.post("https://openrouter.ai/api/v1/chat/completions").mock(
        return_value=httpx.Response(
            200,
            json={
                "choices": [],
                "usage": {"prompt_tokens": 900, "completion_tokens": 120},
            },
        )
    )
    budget = AsyncMock()
    client = OpenRouterClient(
        api_key="test-key",
        model="m1",
        pricing_map={"m1": {"prompt_per_1k": 0.002, "completion_per_1k": 0.004}},
        budget_guard=budget,
    )

    result = await client.analyze_post(title="Title", body="Body", post_id="reddit:bad-shape")

    assert result is None
    budget.record_usage.assert_awaited_once()
    call_kwargs = budget.record_usage.await_args.kwargs
    assert call_kwargs["model"] == "m1"
    assert call_kwargs["operation"] == "classify_primary"
    assert call_kwargs["prompt_tokens"] == 900
    assert call_kwargs["completion_tokens"] == 120
    assert call_kwargs["cost_usd"] == 0.00228
    assert call_kwargs["post_id"] == "reddit:bad-shape"


async def test_usage_tracking_failure_does_not_drop_valid_result(respx_mock, caplog):
    respx_mock.post("https://openrouter.ai/api/v1/chat/completions").mock(
        return_value=httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": '{"is_monetizable": true, "pain_level": 8, "willingness_to_pay": 8, "niche_category": "DevTools", "competitor_tags": [], "summary": "Need retry flow", "category": "complaint", "severity": "high"}'
                        }
                    }
                ],
                "usage": {"prompt_tokens": 1200, "completion_tokens": 300},
            },
        )
    )
    budget = AsyncMock()
    budget.record_usage.side_effect = RuntimeError("db locked")
    client = OpenRouterClient(api_key="test-key", model="m1", budget_guard=budget)

    result = await client.analyze_post(title="Title", body="Body", post_id="reddit:abc")

    assert result is not None
    assert result.summary == "Need retry flow"
    budget.record_usage.assert_awaited_once()
    assert "llm_usage_record_failed" in caplog.text


async def test_usage_dict_tracking_failure_is_logged_not_raised(caplog):
    budget = AsyncMock()
    budget.record_usage.side_effect = RuntimeError("db locked")
    client = OpenRouterClient(api_key="test-key", model="m1", budget_guard=budget)

    await client._record_usage_from_usage_dict(
        usage={"prompt_tokens": 10, "completion_tokens": 5},
        model="m1",
        operation="classify_primary",
        post_id="reddit:abc",
        prompt_hash="a" * 64,
        fallback_reason=None,
        schema_version="primary_v2",
        candidate_stage="primary",
    )

    budget.record_usage.assert_awaited_once()
    assert "llm_usage_record_failed" in caplog.text


def test_responses_usage_to_dict_tolerates_malformed_token_counts():
    usage = SimpleNamespace(input_tokens="bad", output_tokens=-10)

    assert OpenRouterClient._responses_usage_to_dict(usage) == {
        "prompt_tokens": 0,
        "completion_tokens": 0,
    }


def test_responses_usage_to_dict_tolerates_overflow_token_counts():
    usage = SimpleNamespace(input_tokens=float("inf"), output_tokens=25)

    assert OpenRouterClient._responses_usage_to_dict(usage) == {
        "prompt_tokens": 0,
        "completion_tokens": 25,
    }


async def test_legacy_usage_tracking_records_fallback_reason(respx_mock):
    respx_mock.post("https://openrouter.ai/api/v1/chat/completions").mock(
        return_value=httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": '{"category": "wish", "summary": "Need export feature", "severity": "low"}'
                        }
                    }
                ],
                "usage": {"prompt_tokens": 90, "completion_tokens": 20},
            },
        )
    )
    budget = AsyncMock()
    client = OpenRouterClient(api_key="test-key", model="m1", budget_guard=budget)

    result = await client.analyze_legacy_post(
        title="Wish",
        body="Need CSV",
        post_id="reddit:legacy",
        fallback_reason="primary_invalid",
    )

    assert result is not None
    usage_kwargs = budget.record_usage.await_args.kwargs
    assert usage_kwargs["fallback_reason"] == "primary_invalid"
    assert usage_kwargs["schema_version"] == "legacy_v2"
    assert usage_kwargs["candidate_stage"] == "primary_fallback"


def test_safe_json_load_handles_code_fence():
    raw = """```json
    {"category":"complaint","summary":"x","severity":"low"}
    ```"""
    payload = OpenRouterClient._safe_json_load(raw)
    assert payload["category"] == "complaint"


async def test_retry_bound_derived_from_backoff_tuple_length(respx_mock):
    """Retry count adjusts automatically when RETRY_BACKOFF_SECONDS length changes."""
    from unittest.mock import AsyncMock, patch

    import openrouter as or_module

    # Patch backoff to only 2 entries -> should retry once, give up on attempt 2.
    with patch.object(or_module, "RETRY_BACKOFF_SECONDS", (0.1, 0.2)):
        route = respx_mock.post("https://openrouter.ai/api/v1/chat/completions").mock(
            side_effect=[
                httpx.Response(503),
                httpx.Response(503),
            ]
        )
        client = OpenRouterClient(api_key="test-key", model="test-model")

        with patch("openrouter.asyncio.sleep", new=AsyncMock()) as sleep_mock:
            result = await client.analyze_post(title="T", body="B")

    # 2-entry backoff: attempt 1 retries (sleep once), attempt 2 raises -> caught -> None
    assert result is None
    assert route.call_count == 2
    assert sleep_mock.await_count == 1


async def test_request_error_retries_then_returns_none(respx_mock):
    """Network-level RequestError is retried up to len(RETRY_BACKOFF_SECONDS) times."""
    from unittest.mock import AsyncMock, patch

    route = respx_mock.post("https://openrouter.ai/api/v1/chat/completions").mock(
        side_effect=httpx.ConnectError("connection refused")
    )
    client = OpenRouterClient(api_key="test-key", model="test-model")

    with patch("openrouter.asyncio.sleep", new=AsyncMock()) as sleep_mock:
        result = await client.analyze_post(title="T", body="B")

    from openrouter import RETRY_BACKOFF_SECONDS

    assert result is None
    assert route.call_count == len(RETRY_BACKOFF_SECONDS)
    # sleeps happen on all attempts except the last
    assert sleep_mock.await_count == len(RETRY_BACKOFF_SECONDS) - 1


async def test_oversized_llm_response_returns_none(respx_mock):
    respx_mock.post("https://openrouter.ai/api/v1/chat/completions").mock(
        return_value=httpx.Response(200, content=b"x" * 17)
    )
    client = OpenRouterClient(api_key="test-key", model="test-model", max_response_bytes=16)

    result = await client.analyze_post(title="T", body="B")

    assert result is None


async def test_non_retryable_http_error_does_not_retry(respx_mock):
    """A 400 Bad Request is not in RETRYABLE_STATUS_CODES and must not be retried."""
    from unittest.mock import AsyncMock, patch

    route = respx_mock.post("https://openrouter.ai/api/v1/chat/completions").mock(
        return_value=httpx.Response(400)
    )
    client = OpenRouterClient(api_key="test-key", model="test-model")

    with patch("openrouter.asyncio.sleep", new=AsyncMock()) as sleep_mock:
        result = await client.analyze_post(title="T", body="B")

    assert result is None
    assert route.call_count == 1
    assert sleep_mock.await_count == 0

