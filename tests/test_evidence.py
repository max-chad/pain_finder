from dataclasses import FrozenInstanceError

import pytest

from evidence import EvidenceSource, VerifiedEvidence, verify_evidence_spans


def test_verifies_exact_title_match():
    source = EvidenceSource(
        source_type="title",
        text="Manual invoice approvals block every enterprise deal",
        post_id="reddit:p1",
        permalink="https://reddit.test/p1",
        created_utc=1776470400,
    )

    verified = verify_evidence_spans(["Manual invoice approvals"], [source])

    assert verified == [
        VerifiedEvidence(
            quote="Manual invoice approvals",
            source_type="title",
            post_id="reddit:p1",
            comment_id=None,
            permalink="https://reddit.test/p1",
            created_utc=1776470400,
            match_type="exact",
            match_confidence=1.0,
        )
    ]


def test_verifies_exact_body_match():
    source = EvidenceSource(
        source_type="body",
        text="Our support team still copy/pastes refunds into three systems.",
        post_id="reddit:p2",
        permalink="https://reddit.test/p2",
    )

    verified = verify_evidence_spans(["copy/pastes refunds"], [source])

    assert verified[0].quote == "copy/pastes refunds"
    assert verified[0].source_type == "body"
    assert verified[0].post_id == "reddit:p2"
    assert verified[0].match_type == "exact"
    assert verified[0].match_confidence == 1.0


def test_verifies_exact_comment_match():
    source = EvidenceSource(
        source_type="comment",
        text="Same here, we export CSVs every Friday as a workaround.",
        post_id="reddit:p3",
        comment_id="c9",
        permalink="https://reddit.test/p3#c9",
        created_utc=1776556800,
    )

    verified = verify_evidence_spans(["we export CSVs every Friday"], [source])

    assert verified[0].source_type == "comment"
    assert verified[0].post_id == "reddit:p3"
    assert verified[0].comment_id == "c9"
    assert verified[0].permalink == "https://reddit.test/p3#c9"
    assert verified[0].created_utc == 1776556800
    assert verified[0].match_type == "exact"


def test_uses_fuzzy_match_for_whitespace_and_punctuation_variants():
    source = EvidenceSource(
        source_type="body",
        text="Manual approvals, for renewals, still block deals.",
        post_id="reddit:p4",
        permalink="https://reddit.test/p4",
    )

    verified = verify_evidence_spans(["manual approvals for renewals still block deals"], [source])

    assert verified[0].quote == "manual approvals for renewals still block deals"
    assert verified[0].source_type == "body"
    assert verified[0].post_id == "reddit:p4"
    assert verified[0].match_type == "fuzzy"
    assert 0 < verified[0].match_confidence < 1.0


def test_marks_false_spans_as_none_without_source_location():
    source = EvidenceSource(
        source_type="body",
        text="The thread is only asking for podcast recommendations.",
        post_id="reddit:p5",
        permalink="https://reddit.test/p5",
    )

    verified = verify_evidence_spans(["we lose customers every week"], [source])

    assert verified == [
        VerifiedEvidence(
            quote="we lose customers every week",
            source_type="",
            post_id="",
            comment_id=None,
            permalink="",
            created_utc=None,
            match_type="none",
            match_confidence=0.0,
        )
    ]


def test_preserves_duplicate_quotes_as_duplicate_results():
    source = EvidenceSource(
        source_type="title",
        text="Zendesk exports keep failing for our support team",
        post_id="reddit:p6",
        permalink="https://reddit.test/p6",
    )

    verified = verify_evidence_spans(["exports keep failing", "exports keep failing"], [source])

    assert len(verified) == 2
    assert [item.quote for item in verified] == ["exports keep failing", "exports keep failing"]
    assert [item.match_type for item in verified] == ["exact", "exact"]


def test_returns_empty_list_for_empty_evidence():
    source = EvidenceSource(
        source_type="body",
        text="Manual invoicing is still painful.",
        post_id="reddit:p7",
    )

    assert verify_evidence_spans([], [source]) == []


def test_dataclasses_are_frozen():
    source = EvidenceSource(source_type="title", text="Pain", post_id="reddit:p8")

    with pytest.raises(FrozenInstanceError):
        source.text = "Changed"
