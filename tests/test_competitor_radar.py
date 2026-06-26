from competitor_radar import build_competitor_failure_radar, failure_signals_for_row


def test_builds_competitor_failure_radar_from_promotion_eligible_exact_evidence():
    rows = [
        {
            "post_id": "p1",
            "title": "Salesforce pricing doubled and CSV export fails",
            "summary": "Manual workaround in spreadsheets",
            "competitor_tags": ["salesforce"],
            "first_handness": "first_hand",
            "buyer_authority_score": 0.9,
            "opportunity_score": 81,
            "verified_evidence": [
                {"quote": "CSV export fails", "match_type": "exact"},
            ],
            "score_components": {"promotion_eligible": True},
        },
        {
            "post_id": "p2",
            "title": "Generic CRM listicle",
            "competitor_tags": ["hubspot"],
            "verified_evidence": [],
            "score_components": {"promotion_eligible": True},
        },
    ]

    radar = build_competitor_failure_radar(rows)

    assert len(radar) == 1
    assert radar[0].tool == "salesforce"
    assert "Pricing pain (1)" in radar[0].rendered_signal_counts()
    assert "Workaround (1)" in radar[0].rendered_signal_counts()


def test_failure_signals_for_row_detects_switching_and_support_failures():
    signals = failure_signals_for_row(
        {
            "title": "Zendesk support is down and we cannot export",
            "summary": "We need a manual workaround",
            "competitor_tags": ["zendesk", "intercom"],
        },
        primary_tool="zendesk",
    )

    assert "lock_in_switching_churn" in signals
    assert "reliability_support_failure" in signals
    assert "alternative_tool_mentions" in signals
