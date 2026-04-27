from __future__ import annotations

import json
from typing import Any

FEEDBACK_VALUES = (
    "useful",
    "not_a_pain",
    "duplicate",
    "too_generic",
    "wrong_segment",
    "bad_evidence",
)
FEEDBACK_VALUE_SET = frozenset(FEEDBACK_VALUES)

FEEDBACK_LABEL_SUGGESTIONS: dict[str, dict[str, Any]] = {
    "useful": {"feedback_useful": True},
    "not_a_pain": {"feedback_useful": False, "is_pain": False},
    "duplicate": {"feedback_useful": False, "review_hint": "duplicate"},
    "too_generic": {"feedback_useful": False, "hard_negative_type": "generic_recommendation"},
    "wrong_segment": {"feedback_useful": False, "hard_negative_type": "out_of_scope"},
    "bad_evidence": {"feedback_useful": False, "evidence_relevance": "irrelevant"},
}

FEEDBACK_REVIEW_REASONS: dict[str, str] = {
    "useful": "User marked this item useful; review before turning it into eval labels.",
    "not_a_pain": "User marked this item as not a pain.",
    "duplicate": "User marked this item as a duplicate.",
    "too_generic": "User marked this item as too generic.",
    "wrong_segment": "User marked this item as the wrong segment.",
    "bad_evidence": "User marked this item as having bad evidence.",
}


def normalize_feedback_value(value: Any) -> str:
    normalized = str(value or "").strip().lower()
    if normalized not in FEEDBACK_VALUE_SET:
        raise ValueError(f"Unsupported feedback_value: {value!r}")
    return normalized


def empty_feedback_summary() -> dict[str, int]:
    return {value: 0 for value in FEEDBACK_VALUES}


def _decode_json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if not isinstance(value, str) or not value.strip():
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _decode_json_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if not isinstance(value, str) or not value.strip():
        return []
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return []
    return parsed if isinstance(parsed, list) else []


def build_feedback_label_review_row(
    feedback_event: dict[str, Any],
    *,
    pain_point: dict[str, Any] | None = None,
) -> dict[str, Any]:
    value = normalize_feedback_value(feedback_event.get("feedback_value"))
    post_id = str(feedback_event.get("post_id") or "").strip()
    if not post_id:
        raise ValueError("feedback row is missing post_id")
    pain_point = pain_point or {}
    metadata = _decode_json_object(feedback_event.get("metadata_json") or feedback_event.get("metadata"))
    verified_evidence = _decode_json_list(
        pain_point.get("verified_evidence_json") or pain_point.get("verified_evidence")
    )

    return {
        "review_type": "feedback_label_review",
        "review_status": "pending",
        "feedback_event_id": feedback_event.get("id") or feedback_event.get("feedback_event_id"),
        "post_id": post_id,
        "feedback_value": value,
        "feedback_source": str(feedback_event.get("source") or "manual"),
        "feedback_created_at": feedback_event.get("created_at"),
        "feedback_metadata": metadata,
        "review_reason": FEEDBACK_REVIEW_REASONS[value],
        "label_suggestions": dict(FEEDBACK_LABEL_SUGGESTIONS[value]),
        "requires_human_review": True,
        "promotion_eligible": False,
        "source": {
            "subreddit": str(pain_point.get("subreddit") or ""),
            "title": str(pain_point.get("title") or ""),
            "body": str(pain_point.get("body") or ""),
            "url": str(pain_point.get("url") or ""),
            "source": str(pain_point.get("source") or ""),
            "triage_status": str(pain_point.get("triage_status") or ""),
            "evidence_quality": str(pain_point.get("evidence_quality") or ""),
            "verified_evidence": verified_evidence,
            "opportunity_score": pain_point.get("opportunity_score"),
        },
    }
