from dataclasses import FrozenInstanceError

import pytest

from evidence import EvidenceSource, VerifiedEvidence, verify_evidence_spans


def test_verifies_exact_body_match():
    source = EvidenceSource(
        source_type="body",
        text="Our support team still copy/pastes refunds into three systems.",
        post_id="reddit:p1",
        permalink="https://reddit.test/p1",
    )

    verified = verify_evidence_spans(["copy/pastes refunds"], [source])

    assert verified[0] == VerifiedEvidence(
        quote="copy/pastes refunds",
        source_type="body",
        post_id="reddit:p1",
        comment_id=None,
        permalink="https://reddit.test/p1",
        match_type="exact",
        match_confidence=1.0,
        created_utc=None,
    )


def test_uses_fuzzy_match_for_whitespace_and_punctuation_variants():
    source = EvidenceSource(
        source_type="body",
        text="Manual approvals, for renewals, still block deals.",
        post_id="reddit:p2",
    )

    verified = verify_evidence_spans(["manual approvals for renewals still block deals"], [source])

    assert verified[0].match_type == "fuzzy"
    assert verified[0].match_confidence == 0.9


def test_marks_false_spans_as_none_without_source_location():
    source = EvidenceSource(source_type="body", text="Only asking for podcast recommendations.", post_id="reddit:p3")

    verified = verify_evidence_spans(["we lose customers every week"], [source])

    assert verified[0].match_type == "none"
    assert verified[0].post_id == ""


def test_dataclasses_are_frozen():
    source = EvidenceSource(source_type="title", text="Pain", post_id="reddit:p4")

    with pytest.raises(FrozenInstanceError):
        source.text = "Changed"
