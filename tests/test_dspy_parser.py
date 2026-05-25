from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from budget import BudgetCapReachedError
from dspy_parser import DSPyRedditPainParser
from scraper import Post


def test_is_available_reflects_installed_dspy_package():
    with patch("dspy_parser.importlib.util.find_spec", return_value=None):
        assert DSPyRedditPainParser.is_available() is False
    with patch("dspy_parser.importlib.util.find_spec", return_value=object()):
        assert DSPyRedditPainParser.is_available() is True


def test_model_name_for_codex_provider_uses_openai_prefix():
    parser = DSPyRedditPainParser(api_key="test-key", provider="codex", model="gpt-5.3-spark")

    assert parser._model_name_for_provider() == "openai/gpt-5.3-spark"


def test_coerce_prediction_normalizes_strings_into_analysis_result():
    parser = DSPyRedditPainParser(api_key="test-key", provider="codex", model="gpt-5.3-spark")
    prediction = SimpleNamespace(
        category="complaint",
        severity="high",
        summary="Teams are still reconciling invoices manually",
        is_monetizable="true",
        pain_level="9",
        willingness_to_pay="8",
        niche_category="Finance Ops",
        competitor_tags_csv=" QuickBooks , hubspot, quickbooks ",
    )

    result = parser._coerce_prediction(prediction)

    assert result is not None
    assert result.category == "complaint"
    assert result.severity == "high"
    assert result.is_monetizable is True
    assert result.pain_level == 9
    assert result.willingness_to_pay == 8
    assert result.niche_category == "Finance Ops"
    assert result.competitor_tags == ["quickbooks", "hubspot"]


@pytest.mark.asyncio
async def test_analyze_post_checks_budget_guard_before_dspy_call(monkeypatch):
    budget_guard = AsyncMock()
    parser = DSPyRedditPainParser(
        api_key="test-key",
        provider="codex",
        model="gpt-5.3-spark",
        budget_guard=budget_guard,
    )
    parser._dspy = SimpleNamespace(settings=SimpleNamespace(context=lambda lm: _NullContext()))
    parser._lm = object()

    def fake_program(**kwargs):
        return SimpleNamespace(
            category="complaint",
            severity="high",
            summary="Teams reconcile invoices manually",
            is_monetizable="true",
            pain_level="9",
            willingness_to_pay="8",
            niche_category="Finance Ops",
            competitor_tags_csv="quickbooks",
        )

    monkeypatch.setattr(parser, "_ensure_program", lambda: fake_program)

    result = await parser.analyze_post(_post())

    assert result is not None
    budget_guard.ensure_can_spend.assert_awaited_once_with("dspy_analyze_post")


@pytest.mark.asyncio
async def test_analyze_post_propagates_budget_pause_before_dspy_call(monkeypatch):
    budget_guard = AsyncMock()
    budget_guard.ensure_can_spend.side_effect = BudgetCapReachedError("paused")
    parser = DSPyRedditPainParser(
        api_key="test-key",
        provider="codex",
        model="gpt-5.3-spark",
        budget_guard=budget_guard,
    )
    ensure_program = AsyncMock()
    monkeypatch.setattr(parser, "_ensure_program", ensure_program)

    with pytest.raises(BudgetCapReachedError, match="paused"):
        await parser.analyze_post(_post())

    ensure_program.assert_not_called()


class _NullContext:
    def __enter__(self):
        return None

    def __exit__(self, exc_type, exc, tb):
        return False


def _post() -> Post:
    return Post(
        post_id="reddit:one",
        subreddit="python",
        title="Manual invoice reconciliation hurts",
        body="We spend hours on this every week.",
        url="https://example.com/post",
        score=1,
    )
