from rejected_noise import (
    hard_negative_type_for_signal,
    rejection_reason_counts,
    rejection_reason_label,
)


def test_maps_promotion_rejections_to_hard_negative_types():
    assert (
        hard_negative_type_for_signal(
            post_type="founder_pitch",
            niche_category="Compliance",
            rejection_reason="insufficient_first_hand_evidence",
        )
        == "founder_pitch"
    )
    assert (
        hard_negative_type_for_signal(
            post_type="first_person_pain",
            niche_category="B2C-noise",
            rejection_reason="not_monetizable",
        )
        == "consumer_rant"
    )
    assert rejection_reason_label("ungrounded_evidence") == "no verified evidence"


def test_counts_rejected_noise_reasons_from_rows():
    counts = rejection_reason_counts(
        [
            {"post_type": "founder_pitch", "score_components": {"promotion_eligible": False}},
            {"niche_category": "B2C-noise", "score_components": {"promotion_eligible": False}},
            {"triage_status": "merged"},
        ]
    )

    assert counts == {"duplicate": 1, "founder_pitch": 1, "consumer_rant": 1}
