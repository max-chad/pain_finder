from types import SimpleNamespace

from dspy_parser import DSPyRedditPainParser


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
        post_type="first_person_pain",
        first_handness="first_hand",
        buyer_authority="founder_owner",
        evidence_spans='["manual workflow is awful", "takes hours every week"]',
        confidence="0.76",
        uncertainty_reason="",
        needs_human_review="false",
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
    assert result.post_type == "first_person_pain"
    assert result.first_handness == "first_hand"
    assert result.buyer_authority == "founder_owner"
    assert result.evidence_spans == ["manual workflow is awful", "takes hours every week"]
    assert result.confidence == 0.76
    assert result.needs_human_review is False


def test_coerce_prediction_marks_missing_dspy_evidence_for_review():
    parser = DSPyRedditPainParser(api_key="test-key", provider="codex", model="gpt-5.3-spark")
    prediction = SimpleNamespace(
        category="complaint",
        severity="medium",
        summary="Teams are still reconciling invoices manually",
        is_monetizable="true",
        pain_level="6",
        willingness_to_pay="6",
        niche_category="Finance Ops",
        competitor_tags_csv="quickbooks",
        post_type="first_person_pain",
        first_handness="first_hand",
        buyer_authority="founder_owner",
        evidence_spans="",
        confidence="0.4",
    )

    result = parser._coerce_prediction(prediction)

    assert result is not None
    assert result.evidence_spans == []
    assert result.confidence == 0.4
    assert result.needs_human_review is True
