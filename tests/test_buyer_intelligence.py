from buyer_intelligence import build_buyer_wtp_intelligence


def test_buyer_wtp_intelligence_prefers_exact_quotes_over_cluster_paraphrases():
    intelligence = build_buyer_wtp_intelligence(
        [
            {
                "buyer_authority": "founder_owner",
                "buyer_authority_score": 1.0,
                "willingness_to_pay": 9,
                "exact_verified_quotes": ["I own the budget and would pay for billing reconciliation"],
                "verified_quotes": ["unsupported paraphrase says they would pay"],
                "current_workaround": "paid contractor fixes billing reconciliation monthly",
            }
        ]
    )

    assert intelligence.wtp_evidence_quotes == ("I own the budget and would pay for billing reconciliation",)
    assert "unsupported paraphrase says they would pay" not in intelligence.wtp_evidence_quotes


def test_buyer_wtp_intelligence_requires_explicit_paid_markers_for_paid_workarounds():
    intelligence = build_buyer_wtp_intelligence(
        [
            {
                "buyer_authority": "head_of_ops",
                "buyer_authority_score": 0.94,
                "willingness_to_pay": 8,
                "exact_verified_quotes": ["I would pay to stop invoice approval breaks"],
                "current_workaround": "monthly manual CSV reconciliation before approval",
            },
            {
                "buyer_authority": "head_of_ops",
                "buyer_authority_score": 0.94,
                "willingness_to_pay": 8,
                "exact_verified_quotes": ["I would pay to stop invoice approval breaks"],
                "current_workaround": "unpaid volunteer spreadsheet cleanup",
            },
            {
                "buyer_authority": "head_of_ops",
                "buyer_authority_score": 0.94,
                "willingness_to_pay": 8,
                "exact_verified_quotes": ["I would pay to stop invoice approval breaks"],
                "current_workaround": "manual CSV reconciliation before approval",
            },
            {
                "buyer_authority": "head_of_ops",
                "buyer_authority_score": 0.94,
                "willingness_to_pay": 8,
                "exact_verified_quotes": ["we have budget for this"],
                "current_workaround": "monthly paid contractor cleanup for invoice approvals",
            },
        ]
    )

    assert intelligence.paid_workarounds == ("monthly paid contractor cleanup for invoice approvals",)
