from buyer_intelligence import build_buyer_wtp_intelligence


def test_builds_buyer_wtp_intelligence_from_verified_examples():
    intelligence = build_buyer_wtp_intelligence(
        [
            {
                "buyer_authority": "head_of_ops",
                "buyer_authority_score": 0.94,
                "willingness_to_pay": 9,
                "verified_evidence": [
                    {"quote": "we would pay for this renewal workflow", "match_type": "exact"},
                ],
            },
            {
                "buyer_authority": "manager",
                "buyer_authority_score": 0.82,
                "willingness_to_pay": 7,
                "verified_evidence": [
                    {"quote": "manual workaround takes days", "match_type": "fuzzy"},
                ],
            },
        ]
    )

    assert intelligence.buyer_role_counts == (("head_of_ops", 1), ("manager", 1))
    assert intelligence.avg_buyer_authority == 0.88
    assert intelligence.avg_wtp == 8.0
    assert intelligence.wtp_evidence_quotes == ("we would pay for this renewal workflow",)
