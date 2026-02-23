# tests/test_openrouter.py
import pytest
import httpx
import respx
from openrouter import OpenRouterClient, AnalysisResult


async def test_analyze_returns_structured_result(respx_mock):
    respx_mock.post("https://openrouter.ai/api/v1/chat/completions").mock(
        return_value=httpx.Response(200, json={
            "choices": [{
                "message": {
                    "content": '{"category": "complaint", "summary": "User frustrated with billing", "severity": "high"}'
                }
            }]
        })
    )
    client = OpenRouterClient(api_key="test-key", model="test-model")
    result = await client.analyze_post(
        title="AWS billing is insane",
        body="I got a $500 bill and have no idea why",
    )
    assert result is not None
    assert result.category == "complaint"
    assert result.severity == "high"
    assert "billing" in result.summary


async def test_analyze_handles_malformed_json(respx_mock):
    respx_mock.post("https://openrouter.ai/api/v1/chat/completions").mock(
        return_value=httpx.Response(200, json={
            "choices": [{"message": {"content": "not valid json at all"}}]
        })
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


async def test_analyze_handles_missing_keys_in_response(respx_mock):
    respx_mock.post("https://openrouter.ai/api/v1/chat/completions").mock(
        return_value=httpx.Response(200, json={
            "choices": [{"message": {"content": '{"category": "complaint"}'}}]
        })
    )
    client = OpenRouterClient(api_key="test-key", model="test-model")
    result = await client.analyze_post(title="Test", body="Test body")
    assert result is None


async def test_analysis_result_fields():
    result = AnalysisResult(category="wish", summary="User wants feature X", severity="low")
    assert result.category == "wish"
    assert result.summary == "User wants feature X"
    assert result.severity == "low"


async def test_body_truncated_to_1000_chars(respx_mock):
    # Place a unique marker after the 1000-char boundary
    long_body = "A" * 1000 + "OVERFLOW_MARKER"
    captured_requests = []

    def capture(request):
        captured_requests.append(request)
        return httpx.Response(200, json={
            "choices": [{"message": {"content": '{"category": "complaint", "summary": "s", "severity": "low"}'}}]
        })

    respx_mock.post("https://openrouter.ai/api/v1/chat/completions").mock(side_effect=capture)
    client = OpenRouterClient(api_key="test-key", model="test-model")
    await client.analyze_post(title="Test", body=long_body)

    import json
    req_body = json.loads(captured_requests[0].content)
    prompt = req_body["messages"][0]["content"]
    assert "OVERFLOW_MARKER" not in prompt


async def test_analyze_rejects_invalid_category(respx_mock):
    respx_mock.post("https://openrouter.ai/api/v1/chat/completions").mock(
        return_value=httpx.Response(200, json={
            "choices": [{"message": {"content": '{"category": "frustration", "summary": "s", "severity": "high"}'}}]
        })
    )
    client = OpenRouterClient(api_key="test-key", model="test-model")
    result = await client.analyze_post(title="Test", body="Test body")
    assert result is None


async def test_analyze_handles_empty_choices(respx_mock):
    respx_mock.post("https://openrouter.ai/api/v1/chat/completions").mock(
        return_value=httpx.Response(200, json={"choices": []})
    )
    client = OpenRouterClient(api_key="test-key", model="test-model")
    result = await client.analyze_post(title="Test", body="Test body")
    assert result is None


async def test_analyze_retries_transient_http_errors(respx_mock):
    from unittest.mock import AsyncMock, patch

    route = respx_mock.post("https://openrouter.ai/api/v1/chat/completions").mock(
        side_effect=[
            httpx.Response(503),
            httpx.Response(503),
            httpx.Response(
                200,
                json={
                    "choices": [
                        {
                            "message": {
                                "content": '{"category": "complaint", "summary": "Retry worked", "severity": "medium"}'
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
    assert route.call_count == 3
    assert sleep_mock.await_count == 2
