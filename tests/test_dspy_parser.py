from types import SimpleNamespace
from unittest.mock import patch

from dspy_parser import DSPyRedditPainParser


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
