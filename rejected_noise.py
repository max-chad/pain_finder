from __future__ import annotations

import json
from collections import Counter
from typing import Any

HARD_NEGATIVE_TYPES = {
    "generic_question",
    "consumer_rant",
    "founder_pitch",
    "news_analysis",
    "low_context",
    "no_evidence",
    "solved_issue",
    "shill_risk",
    "duplicate",
    "discarded",
    "not_monetizable",
    "out_of_scope",
}

_REASON_ALIASES = {
    "": "",
    "none": "",
    "ungrounded_evidence": "no_evidence",
    "no_verified_exact_quote": "no_evidence",
    "no_exact_quote": "no_evidence",
    "missing_exact_quote": "no_evidence",
    "missing_verified_quote": "no_evidence",
    "no_quote": "no_evidence",
    "weak_quote": "no_evidence",
    "unsupported_post_type": "news_analysis",
    "insufficient_first_hand_evidence": "low_context",
    "generic": "generic_question",
    "generic_advice": "generic_question",
    "advice_thread": "generic_question",
    "b2c": "consumer_rant",
    "b2c_noise": "consumer_rant",
    "consumer": "consumer_rant",
    "consumer_complaint": "consumer_rant",
    "vendor_promotion": "shill_risk",
    "shill": "shill_risk",
    "already_solved": "solved_issue",
    "merged": "duplicate",
}

_REASON_LABELS = {
    "generic_question": "generic question",
    "consumer_rant": "consumer rant",
    "founder_pitch": "founder pitch",
    "news_analysis": "news or analysis",
    "low_context": "low context",
    "no_evidence": "no verified evidence",
    "solved_issue": "solved issue",
    "shill_risk": "shill risk",
    "duplicate": "duplicate",
    "discarded": "discarded",
    "not_monetizable": "not monetizable",
    "out_of_scope": "out of scope",
}

_REASON_PRIORITY = {
    "duplicate": 0,
    "founder_pitch": 1,
    "news_analysis": 2,
    "generic_question": 3,
    "consumer_rant": 4,
    "low_context": 5,
    "no_evidence": 6,
    "not_monetizable": 7,
    "solved_issue": 8,
    "shill_risk": 9,
    "discarded": 10,
    "out_of_scope": 11,
}


def normalize_rejection_reason(reason: Any) -> str:
    text = str(reason or "").strip().lower().replace("-", "_").replace(" ", "_")
    normalized = _REASON_ALIASES.get(text, text)
    return normalized if normalized in HARD_NEGATIVE_TYPES else normalized


def rejection_reason_label(reason: Any) -> str:
    normalized = normalize_rejection_reason(reason)
    return _REASON_LABELS.get(normalized, normalized.replace("_", " "))


def rejection_reason_priority(reason: Any) -> int:
    return _REASON_PRIORITY.get(normalize_rejection_reason(reason), 99)


def hard_negative_type_for_signal(*, post_type: str, niche_category: str, rejection_reason: str | None) -> str:
    if post_type == "founder_pitch":
        return "founder_pitch"
    if post_type == "news_analysis":
        return "news_analysis"
    if str(niche_category or "").strip().lower() in {"b2c-noise", "b2c_noise", "consumer_rant"}:
        return "consumer_rant"
    return normalize_rejection_reason(rejection_reason)


def score_components_from_row(row: dict[str, Any]) -> dict[str, Any]:
    raw = row.get("score_components")
    if isinstance(raw, dict):
        return raw
    raw = row.get("score_components_json")
    if not isinstance(raw, str) or not raw.strip():
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def rejected_noise_reason(row: dict[str, Any]) -> str:
    triage_status = str(row.get("triage_status") or "").strip().lower()
    if triage_status == "merged":
        return "duplicate"
    components = score_components_from_row(row)
    component_reason = normalize_rejection_reason(
        components.get("hard_negative_type") or components.get("evidence_rejection_reason")
    )
    if component_reason:
        return component_reason
    if _coerce_bool(components.get("promotion_eligible")) or _coerce_bool(row.get("promotion_eligible")):
        return ""
    haystack = " ".join(
        str(row.get(key) or "").strip().lower()
        for key in ("category", "post_type", "niche_category", "title", "summary")
    )
    if "founder_pitch" in haystack or "founder pitch" in haystack:
        return "founder_pitch"
    if "news_analysis" in haystack or "market recap" in haystack:
        return "news_analysis"
    if any(token in haystack for token in ("consumer_rant", "b2c", "consumer app")):
        return "consumer_rant"
    if triage_status == "discarded":
        return "discarded"
    return "no_evidence"


def annotate_rejected_noise_row(row: dict[str, Any]) -> dict[str, Any]:
    annotated = dict(row)
    reason = rejected_noise_reason(annotated)
    annotated["rejection_reason"] = reason
    annotated["rejection_reason_label"] = rejection_reason_label(reason) if reason else ""
    return annotated


def rejection_reason_counts(rows: list[dict[str, Any]]) -> dict[str, int]:
    counter = Counter(
        row["rejection_reason"]
        for row in (annotate_rejected_noise_row(row) for row in rows)
        if row.get("rejection_reason")
    )
    return dict(sorted(counter.items(), key=lambda item: (rejection_reason_priority(item[0]), item[0])))


def _coerce_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y", "on"}
    return False
