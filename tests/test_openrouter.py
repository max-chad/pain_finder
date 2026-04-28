import json
from unittest.mock import AsyncMock

import httpx
import respx

from openrouter import AnalysisResult, DeepDiveResult, OpenRouterClient, PainDetectionResult, ResearchActionResult


def _primary_payload(**overrides):
    payload = {
        "is_monetizable": True,
        "pain_level": 8,
        "willingness_to_pay": 8,
        "niche_category": "DevTools",
        "competitor_tags": [],
        "summary": "Manual process",
        "category": "complaint",
        "severity": "high",
        "post_type": "first_person_pain",
        "first_handness": "first_hand",
        "buyer_authority": "founder_owner",
        "pain_type": "workflow",
        "expression_type": "first_person_complaint",
        "user_context": "Ops founder running manual workflows",
        "intensity": 8,
        "frequency": 7,
        "urgency": 8,
        "current_workaround": "Manual spreadsheet reconciliation",
        "incumbent_failure": "Existing sync tools lose records",
        "evidence_spans": ["Manual process is painful"],
        "evidence_quality": "exact_quote",
        "opportunity_type": "current_opportunity",
        "confidence": 0.8,
        "uncertainty_reason": "",
        "needs_human_review": False,
    }
    payload.update(overrides)
    return payload


def _primary_content(**overrides):
    return json.dumps(_primary_payload(**overrides))


def _pain_detection_payload(**overrides):
    payload = {
        "is_pain": True,
        "is_noise": False,
        "post_type": "solution_request",
        "operational_consequence": "reconciliation",
        "confidence": 0.82,
        "uncertainty_reason": "",
        "needs_human_review": False,
    }
    payload.update(overrides)
    return payload


def _pain_detection_content(**overrides):
    return json.dumps(_pain_detection_payload(**overrides))


async def test_analyze_pain_detection_returns_stage_result_and_records_stage_usage(respx_mock):
    respx_mock.post("https://openrouter.ai/api/v1/chat/completions").mock(
        return_value=httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": _pain_detection_content(
                                post_type="solution_request",
                                operational_consequence="csv_spreadsheet_handoff",
                                confidence=0.74,
                            )
                        }
                    }
                ],
                "usage": {"prompt_tokens": 140, "completion_tokens": 30},
            },
        )
    )
    budget = AsyncMock()
    client = OpenRouterClient(api_key="key", model="m1", budget_guard=budget)

    result = await client.analyze_pain_detection(
        title="How are you reconciling payout CSVs?",
        body="Our ops team copy/pastes between Stripe and QuickBooks every week.",
        post_id="reddit:stage",
    )

    assert isinstance(result, PainDetectionResult)
    assert result.is_pain is True
    assert result.is_noise is False
    assert result.post_type == "solution_request"
    assert result.operational_consequence == "csv_spreadsheet_handoff"
    assert result.confidence == 0.74
    budget.record_usage.assert_awaited_once()
    call_kwargs = budget.record_usage.await_args.kwargs
    assert call_kwargs["operation"] == "pain_detection"
    assert call_kwargs["schema_version"] == "pain_detection_v1"
    assert call_kwargs["candidate_stage"] == "pain_detection"


def test_parse_pain_detection_rejects_invalid_or_ambiguous_gate_payload():
    client = OpenRouterClient(api_key="key", model="m1")

    assert client._parse_pain_detection_result(_pain_detection_payload(is_pain="yes")) is None
    assert client._parse_pain_detection_result(_pain_detection_payload(post_type="buying_question")) is None
    assert client._parse_pain_detection_result(_pain_detection_payload(operational_consequence="legal_compliance")) is None
    assert client._parse_pain_detection_result(_pain_detection_payload(is_pain=True, is_noise=True)) is None


async def test_analyze_returns_primary_b2b_result(respx_mock):
    respx_mock.post("https://openrouter.ai/api/v1/chat/completions").mock(
        return_value=httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": _primary_content(
                                willingness_to_pay=9,
                                niche_category="E-commerce",
                                competitor_tags=["shopify"],
                                summary="Inventory sync is failing for stores",
                                evidence_spans=["stock sync lags", "we lose sales"],
                                pain_type="integration",
                                expression_type="first_person_complaint",
                                user_context="Shopify merchant losing sales",
                                intensity=9,
                                frequency=8,
                                urgency=9,
                                current_workaround="Manual stock checks",
                                incumbent_failure="Shopify stock sync lags",
                                evidence_quality="multi_quote",
                                opportunity_type="current_opportunity",
                                confidence=0.73,
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
    assert result.pain_type == "integration"
    assert result.expression_type == "first_person_complaint"
    assert result.user_context == "Shopify merchant losing sales"
    assert result.intensity == 9
    assert result.frequency == 8
    assert result.urgency == 9
    assert result.current_workaround == "Manual stock checks"
    assert result.incumbent_failure == "Shopify stock sync lags"
    assert result.evidence_quality == "multi_quote"
    assert result.opportunity_type == "current_opportunity"
    assert result.confidence == 0.73
    assert result.uncertainty_reason == ""
    assert result.needs_human_review is False


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


def test_parse_primary_coerces_review_flag():
    client = OpenRouterClient(api_key="test-key", model="test-model")

    result = client._parse_primary_result(
        _primary_payload(
            willingness_to_pay=9,
            niche_category="E-commerce",
            summary="Inventory sync keeps failing",
            evidence_spans=["stock sync lags"],
            confidence=0.42,
            uncertainty_reason="needs review",
            needs_human_review="true",
        )
    )

    assert result is not None
    assert result.confidence == 0.42
    assert result.needs_human_review is True


def test_parse_primary_rejects_nonfinite_confidence():
    client = OpenRouterClient(api_key="test-key", model="test-model")

    result = client._parse_primary_result(_primary_payload(confidence=float("nan")))

    assert result is None


def test_parse_primary_rejects_invalid_review_flag():
    client = OpenRouterClient(api_key="test-key", model="test-model")

    result = client._parse_primary_result(_primary_payload(evidence_spans=["stock sync lags"], needs_human_review="maybe"))

    assert result is None


def test_parse_primary_rejects_missing_extended_schema_fields():
    client = OpenRouterClient(api_key="test-key", model="test-model")
    payload = _primary_payload()
    payload.pop("pain_type")

    result = client._parse_primary_result(payload)

    assert result is None


def test_parse_primary_rejects_invalid_extended_schema_fields():
    client = OpenRouterClient(api_key="test-key", model="test-model")
    payload = _primary_payload(intensity=11, evidence_quality="model_guess")

    result = client._parse_primary_result(payload)

    assert result is None


def test_parse_primary_accepts_wave5_taxonomy_values():
    client = OpenRouterClient(api_key="test-key", model="test-model")

    result = client._parse_primary_result(
        _primary_payload(
            pain_type="integration_gap",
            expression_type="feature_request",
            current_workaround="spreadsheet",
            incumbent_failure="explicit_competitor_failure",
            opportunity_type="automation",
        )
    )

    assert result is not None
    assert result.pain_type == "integration_gap"
    assert result.expression_type == "feature_request"
    assert result.current_workaround == "spreadsheet"
    assert result.incumbent_failure == "explicit_competitor_failure"
    assert result.opportunity_type == "automation"


def test_parse_primary_rejects_missing_required_evidence_review_fields():
    client = OpenRouterClient(api_key="test-key", model="test-model")

    for required_field in ["evidence_spans", "confidence", "uncertainty_reason", "needs_human_review"]:
        payload = _primary_payload()
        payload.pop(required_field)
        assert client._parse_primary_result(payload) is None, required_field


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


async def test_generate_research_action_returns_structured_cluster_action(respx_mock):
    payload = {
        "interview_questions": [
            "How often do approval CSV handoffs break?",
            "What happens when CRM sync misses an approval status?",
            "What would make a concierge fix worth trying this week?",
        ],
        "icp_hypothesis": "RevOps managers at mid-market B2B teams owning onboarding approvals.",
        "mvp_wedge": "Concierge CSV-to-approval reconciliation for HubSpot/Salesforce handoffs.",
        "messaging_angle": "Stop reconciling onboarding CSVs by hand before approvals.",
        "why_now": "Fresh verified complaints plus multi-source coverage suggest active workflow breakage.",
        "risks_unknowns": [
            "Confirm this is budgeted pain rather than one-off cleanup.",
            "Validate CRM-specific integration constraints before building automation.",
        ],
        "manual_validation_step": "Interview 5 RevOps owners and manually reconcile one real handoff before writing code.",
        "evidence_post_ids": ["action-supported"],
    }
    captured_requests = []

    def capture(request):
        captured_requests.append(request)
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": json.dumps(payload)}}]},
        )

    respx_mock.post("https://openrouter.ai/api/v1/chat/completions").mock(side_effect=capture)
    client = OpenRouterClient(api_key="key", model="test-model", cluster_model="cluster-model")

    result = await client.generate_research_action(
        context="cluster context with verified exact quotes",
        cluster_key="revops-csv-approvals",
        eligible_post_ids=["action-supported"],
    )

    assert isinstance(result, ResearchActionResult)
    assert result.interview_questions[0].startswith("How often")
    assert result.icp_hypothesis.startswith("RevOps managers")
    assert result.mvp_wedge.startswith("Concierge CSV")
    assert result.manual_validation_step.startswith("Interview 5")
    assert result.evidence_post_ids == ["action-supported"]
    request_body = json.loads(captured_requests[0].content)
    assert request_body["model"] == "cluster-model"
    assert "action-supported" in request_body["messages"][-1]["content"]


def test_parse_research_action_rejects_incomplete_payload():
    client = OpenRouterClient(api_key="key", model="test-model")

    result = client._parse_research_action_result(
        {
            "interview_questions": ["Who owns this workflow?"],
            "icp_hypothesis": "Ops managers",
            "mvp_wedge": "Concierge workflow",
            "messaging_angle": "Stop manual work",
            "why_now": "Fresh pain",
            "risks_unknowns": ["Unknown budget"],
        }
    )

    assert result is None


def test_parse_research_action_rejects_unanchored_or_malformed_evidence_payload():
    client = OpenRouterClient(api_key="key", model="test-model")
    payload = {
        "interview_questions": ["Who owns this workflow?", "How often does it break?"],
        "icp_hypothesis": "Ops managers",
        "mvp_wedge": "Concierge workflow",
        "messaging_angle": "Stop manual reconciliation",
        "why_now": "Fresh exact quotes",
        "risks_unknowns": ["Unknown budget"],
        "manual_validation_step": "Manually solve one case",
        "evidence_post_ids": ["weak-row"],
    }

    assert client._parse_research_action_result(payload, eligible_post_ids=["eligible-row"]) is None

    malformed = dict(payload)
    malformed["evidence_post_ids"] = ["eligible-row"]
    malformed["icp_hypothesis"] = {"not": "a string"}
    assert client._parse_research_action_result(malformed, eligible_post_ids=["eligible-row"]) is None


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
                            "content": _primary_content(is_monetizable=False, pain_level=0, willingness_to_pay=0, niche_category="", summary="s", severity="low", evidence_quality="no_quote", opportunity_type="not_opportunity")
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
                            "content": _primary_content(pain_level=6, willingness_to_pay=7, niche_category="Ops", summary="Manual process", severity="medium")
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
                            "content": _primary_content(pain_level=6, willingness_to_pay=7, niche_category="Ops", summary="Manual process", severity="medium")
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
                            "content": _primary_content(pain_level=7, willingness_to_pay=8, niche_category="Ops", summary="Works", severity="medium")
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
            payload = _primary_content(
                pain_level=7,
                willingness_to_pay=8,
                niche_category="Ops",
                summary="From stream",
                severity="medium",
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
                                "content": _primary_content(pain_level=6, willingness_to_pay=7, niche_category="DevOps", summary="Retry worked", severity="medium")
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
    cache_db.get_cached_llm_payload.return_value = _primary_payload(
        pain_level=7,
        willingness_to_pay=8,
        niche_category="DevOps",
        competitor_tags=["jira"],
        summary="Cached payload",
    )

    budget = AsyncMock()
    client = OpenRouterClient(api_key="test-key", model="m1", budget_guard=budget, cache_db=cache_db)

    result = await client.analyze_post(title="Title", body="Body", post_id="reddit:cached")

    assert result is not None
    assert result.summary == "Cached payload"
    budget.ensure_can_spend.assert_not_called()
    cache_db.get_cached_llm_payload.assert_awaited_once()


@respx.mock
async def test_openrouter_stores_successful_response_in_cache():
    respx.post("https://openrouter.ai/api/v1/chat/completions").mock(
        return_value=httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": _primary_content(summary="Need retry flow", niche_category="DevTools")
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
                                "content": _primary_content(summary="valid", niche_category="DevTools")
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
                            "content": _primary_content(summary="from api", niche_category="DevTools")
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
                            "content": _primary_content(summary="Need retry flow", niche_category="DevTools")
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
    assert call_kwargs["schema_version"] == "primary_v3"
    assert call_kwargs["candidate_stage"] == "primary"
    assert call_kwargs["provider"] == "openrouter"
    assert call_kwargs["request_path"] == "https://openrouter.ai/api/v1/chat/completions"
    assert len(call_kwargs["prompt_hash"]) == 64


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
