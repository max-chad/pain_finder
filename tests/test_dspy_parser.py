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
        pain_type="workflow",
        expression_type="first_person_complaint",
        user_context="Finance ops team reconciling invoices",
        intensity="9",
        frequency="8",
        urgency="7",
        current_workaround="Manual reconciliation in spreadsheets",
        incumbent_failure="QuickBooks and HubSpot do not reconcile invoice state",
        evidence_spans='["manual workflow is awful", "takes hours every week"]',
        evidence_quality="multi_quote",
        opportunity_type="current_opportunity",
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
    assert result.pain_type == "workflow"
    assert result.expression_type == "first_person_complaint"
    assert result.user_context == "Finance ops team reconciling invoices"
    assert result.intensity == 9
    assert result.frequency == 8
    assert result.urgency == 7
    assert result.current_workaround == "Manual reconciliation in spreadsheets"
    assert result.incumbent_failure == "QuickBooks and HubSpot do not reconcile invoice state"
    assert result.evidence_quality == "multi_quote"
    assert result.opportunity_type == "current_opportunity"
    assert result.confidence == 0.76
    assert result.needs_human_review is False


def test_coerce_prediction_accepts_wave5_taxonomy_values():
    parser = DSPyRedditPainParser(api_key="test-key", provider="codex", model="gpt-5.3-spark")
    prediction = SimpleNamespace(
        category="complaint",
        severity="high",
        summary="Inventory reconciliation blocks fulfillment",
        is_monetizable="true",
        pain_level="8",
        willingness_to_pay="9",
        niche_category="E-commerce Ops",
        competitor_tags_csv="netsuite",
        post_type="first_person_pain",
        first_handness="first_hand",
        buyer_authority="head_of_ops",
        pain_type="integration_gap",
        expression_type="feature_request",
        user_context="Ops lead reconciling fulfillment inventory",
        intensity="8",
        frequency="7",
        urgency="8",
        current_workaround="spreadsheet",
        incumbent_failure="explicit_competitor_failure",
        evidence_spans='["reconcile inventory in spreadsheets"]',
        evidence_quality="exact_quote",
        opportunity_type="automation",
        confidence="0.81",
        uncertainty_reason="",
        needs_human_review="false",
    )

    result = parser._coerce_prediction(prediction)

    assert result is not None
    assert result.pain_type == "integration_gap"
    assert result.expression_type == "feature_request"
    assert result.current_workaround == "spreadsheet"
    assert result.incumbent_failure == "explicit_competitor_failure"
    assert result.opportunity_type == "automation"


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
        pain_type="workflow",
        expression_type="first_person_complaint",
        user_context="Finance ops team reconciling invoices",
        intensity="6",
        frequency="5",
        urgency="4",
        current_workaround="Manual reconciliation",
        incumbent_failure="No reliable sync",
        evidence_spans="",
        evidence_quality="no_quote",
        opportunity_type="needs_validation",
        confidence="0.4",
        uncertainty_reason="no evidence spans supplied",
        needs_human_review="true",
    )

    result = parser._coerce_prediction(prediction)

    assert result is not None
    assert result.evidence_spans == []
    assert result.confidence == 0.4
    assert result.needs_human_review is True


def test_coerce_prediction_fails_closed_when_required_extended_field_missing():
    parser = DSPyRedditPainParser(api_key="test-key", provider="codex", model="gpt-5.3-spark")
    prediction = SimpleNamespace(
        category="complaint",
        severity="high",
        summary="Teams are still reconciling invoices manually",
        is_monetizable="true",
        pain_level="9",
        willingness_to_pay="8",
        niche_category="Finance Ops",
        competitor_tags_csv="quickbooks",
        post_type="first_person_pain",
        first_handness="first_hand",
        buyer_authority="founder_owner",
        # pain_type intentionally omitted: DSPy path must not silently default critical fields.
        expression_type="first_person_complaint",
        user_context="Finance ops team reconciling invoices",
        intensity="9",
        frequency="8",
        urgency="7",
        current_workaround="Manual reconciliation",
        incumbent_failure="No reliable sync",
        evidence_spans='["manual workflow is awful"]',
        evidence_quality="exact_quote",
        opportunity_type="current_opportunity",
        confidence="0.76",
        uncertainty_reason="",
        needs_human_review="false",
    )

    assert parser._coerce_prediction(prediction) is None


def test_coerce_prediction_fails_closed_when_required_evidence_review_field_missing():
    parser = DSPyRedditPainParser(api_key="test-key", provider="codex", model="gpt-5.3-spark")
    base_payload = {
        "category": "complaint",
        "severity": "high",
        "summary": "Teams are still reconciling invoices manually",
        "is_monetizable": "true",
        "pain_level": "9",
        "willingness_to_pay": "8",
        "niche_category": "Finance Ops",
        "competitor_tags_csv": "quickbooks",
        "post_type": "first_person_pain",
        "first_handness": "first_hand",
        "buyer_authority": "founder_owner",
        "pain_type": "workflow",
        "expression_type": "first_person_complaint",
        "user_context": "Finance ops team reconciling invoices",
        "intensity": "9",
        "frequency": "8",
        "urgency": "7",
        "current_workaround": "Manual reconciliation",
        "incumbent_failure": "No reliable sync",
        "evidence_spans": '["manual workflow is awful"]',
        "evidence_quality": "exact_quote",
        "opportunity_type": "current_opportunity",
        "confidence": "0.76",
        "uncertainty_reason": "",
        "needs_human_review": "false",
    }

    for required_field in ["evidence_spans", "confidence", "uncertainty_reason", "needs_human_review"]:
        payload = dict(base_payload)
        payload.pop(required_field)
        assert parser._coerce_prediction(SimpleNamespace(**payload)) is None, required_field
