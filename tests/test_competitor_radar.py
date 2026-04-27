from competitor_radar import build_competitor_failure_radar


def test_competitor_failure_radar_groups_failed_incumbent_not_alternative_workaround():
    groups = build_competitor_failure_radar(
        [
            {
                "post_id": "radar-1",
                "title": "HubSpot renewal pricing and lock-in hurt RevOps",
                "summary": "RevOps routes approvals through Airtable after HubSpot renewal pricing doubled.",
                "opportunity_score": 93.0,
                "competitor_tags": '["hubspot", "airtable"]',
                "comment_tool_mentions_json": '["airtable"]',
                "current_workaround": "Airtable approval workaround",
                "incumbent_failure": "HubSpot renewal pricing doubled and contract lock-in blocks switching",
                "verified_evidence_json": '[{"quote":"HubSpot renewal doubled so we use Airtable for approvals","match_type":"exact"}]',
                "evidence_quality": "exact_quote",
                "evidence_match_rate": 1.0,
                "first_handness": "first_hand",
                "buyer_authority_score": 0.94,
                "score_components_json": '{"promotion_eligible": true}',
            }
        ]
    )

    assert [group.tool for group in groups] == ["hubspot"]
    assert groups[0].rendered_signal_counts() == [
        "Pricing pain (1)",
        "Switching/lock-in/churn (1)",
        "Workaround (1)",
        "Alternative-tool mentions (1)",
    ]


def test_competitor_failure_radar_rejects_high_score_rows_without_exact_evidence():
    groups = build_competitor_failure_radar(
        [
            {
                "post_id": "weak-1",
                "title": "HubSpot is awful",
                "summary": "Looks severe but has no verified exact source quote.",
                "opportunity_score": 99.0,
                "competitor_tags": '["hubspot"]',
                "incumbent_failure": "HubSpot support is bad",
                "verified_evidence_json": "[]",
                "evidence_quality": "no_quote",
                "evidence_match_rate": 0.0,
                "first_handness": "first_hand",
                "buyer_authority_score": 1.0,
                "score_components_json": '{"promotion_eligible": true}',
            },
            {
                "post_id": "fuzzy-1",
                "title": "Salesforce support failure",
                "summary": "Has only fuzzy evidence and must stay out of the primary radar.",
                "opportunity_score": 95.0,
                "competitor_tags": '["salesforce"]',
                "incumbent_failure": "Salesforce support fails renewals",
                "verified_evidence_json": '[{"quote":"Salesforce support fails renewals","match_type":"fuzzy"}]',
                "evidence_quality": "weak_quote",
                "evidence_match_rate": 0.6,
                "first_handness": "first_hand",
                "buyer_authority_score": 1.0,
                "score_components_json": '{"promotion_eligible": true}',
            },
        ]
    )

    assert groups == []
