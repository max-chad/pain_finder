from __future__ import annotations

import json
from collections import Counter
from typing import Any

DISPLAY_REJECTED_NOISE_LIMIT = 12
FETCH_REJECTED_NOISE_LIMIT = 50

_REASON_ALIASES = {
    "": "",
    "none": "",
    "no_verified_exact_quote": "no_evidence",
    "no_exact_quote": "no_evidence",
    "missing_exact_quote": "no_evidence",
    "missing_verified_quote": "no_evidence",
    "no_quote": "no_evidence",
    "weak_quote": "no_evidence",
    "low_confidence_needs_review": "low_context",
    "needs_human_review": "low_context",
    "human_review": "low_context",
    "missing_context": "low_context",
    "insufficient_context": "low_context",
    "thin_context": "low_context",
    "generic": "generic_question",
    "generic_advice": "generic_question",
    "advice_thread": "generic_question",
    "b2c": "consumer_rant",
    "consumer": "consumer_rant",
    "consumer_complaint": "consumer_rant",
    "vendor_promotion": "shill_risk",
    "shill": "shill_risk",
    "solved": "solved_issue",
    "already_solved": "solved_issue",
    "duplicate_thread": "duplicate",
    "merged": "duplicate",
}

_REASON_LABELS = {
    "generic_question": "generic question",
    "consumer_rant": "consumer rant",
    "low_context": "low context",
    "no_evidence": "no evidence",
    "solved_issue": "solved issue",
    "shill_risk": "shill risk",
    "duplicate": "duplicate",
    "discarded": "discarded",
    "missing_first_hand_or_buyer_signal": "missing first-hand/buyer signal",
}

_REASON_PRIORITY = {
    "duplicate": 0,
    "generic_question": 1,
    "consumer_rant": 2,
    "low_context": 3,
    "no_evidence": 4,
    "solved_issue": 5,
    "shill_risk": 6,
    "missing_first_hand_or_buyer_signal": 7,
    "discarded": 8,
}


def normalize_rejection_reason(reason: Any) -> str:
    text = str(reason or "").strip().lower().replace("-", "_").replace(" ", "_")
    return _REASON_ALIASES.get(text, text)


def rejection_reason_label(reason: Any) -> str:
    normalized = normalize_rejection_reason(reason)
    return _REASON_LABELS.get(normalized, normalized.replace("_", " "))


def rejection_reason_priority(reason: Any) -> int:
    return _REASON_PRIORITY.get(normalize_rejection_reason(reason), 99)


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


def _json_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if not isinstance(value, str) or not value.strip():
        return []
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return []
    return parsed if isinstance(parsed, list) else []


def _coerce_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _coerce_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y"}
    return False


def exact_evidence_count(row: dict[str, Any]) -> int:
    evidence = row.get("verified_evidence")
    if evidence is None:
        evidence = row.get("verified_evidence_json")
    return sum(
        1
        for item in _json_list(evidence)
        if isinstance(item, dict) and str(item.get("match_type") or "none").strip().lower() == "exact"
    )


def rejected_noise_reason(row: dict[str, Any]) -> str:
    triage_status = str(row.get("triage_status") or "").strip().lower()
    if triage_status == "merged":
        return "duplicate"

    components = score_components_from_row(row)
    component_reason = normalize_rejection_reason(components.get("evidence_rejection_reason"))
    if component_reason:
        return component_reason
    if _coerce_bool(components.get("promotion_eligible")) or _coerce_bool(row.get("promotion_eligible")):
        return ""
    has_verified_exact_evidence = exact_evidence_count(row) > 0
    if has_verified_exact_evidence and not _coerce_bool(row.get("needs_human_review")) and triage_status != "discarded":
        return ""

    haystack = " ".join(
        str(row.get(key) or "").strip().lower()
        for key in ("category", "post_type", "pain_type", "expression_type", "niche_category", "title", "summary")
    )
    if "generic_question" in haystack or "generic question" in haystack:
        return "generic_question"
    if any(token in haystack for token in ("consumer_rant", "consumer rant", "b2c", "consumer app")):
        return "consumer_rant"
    if _coerce_float(row.get("solved_penalty")) >= 0.25 or "solved" in haystack:
        return "solved_issue"
    if _coerce_float(row.get("comment_shill_risk")) >= 0.75:
        return "shill_risk"
    if triage_status == "discarded":
        return "discarded"
    if exact_evidence_count(row) <= 0:
        return "no_evidence"
    if _coerce_bool(row.get("needs_human_review")):
        return "low_context"
    return ""


def annotate_rejected_noise_row(row: dict[str, Any]) -> dict[str, Any]:
    annotated = dict(row)
    reason = rejected_noise_reason(annotated)
    annotated["rejection_reason"] = reason
    annotated["rejection_reason_label"] = rejection_reason_label(reason) if reason else ""
    if reason and not str(annotated.get("evidence_rejection_reason") or "").strip():
        annotated["evidence_rejection_reason"] = reason
    return annotated


def annotate_rejected_noise_rows(rows: Any) -> list[dict[str, Any]]:
    if not isinstance(rows, list):
        return []
    annotated = [annotate_rejected_noise_row(dict(row)) for row in rows if isinstance(row, dict)]
    return [row for row in annotated if row.get("rejection_reason")]


def sort_rejected_noise_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        rows,
        key=lambda row: (
            rejection_reason_priority(row.get("rejection_reason") or row.get("evidence_rejection_reason")),
            -_coerce_float(row.get("opportunity_score")),
            -_coerce_float(row.get("source_created_ts")),
            str(row.get("post_id") or ""),
        ),
    )


def bounded_rejected_noise_rows(rows: Any, *, limit: int = DISPLAY_REJECTED_NOISE_LIMIT) -> list[dict[str, Any]]:
    max_items = max(0, int(limit))
    if max_items <= 0:
        return []
    sorted_rows = sort_rejected_noise_rows(annotate_rejected_noise_rows(rows))
    selected: list[dict[str, Any]] = []
    selected_ids: set[int] = set()
    seen_reasons: set[str] = set()
    for index, row in enumerate(sorted_rows):
        reason = str(row.get("rejection_reason") or "").strip()
        if not reason or reason in seen_reasons:
            continue
        selected.append(row)
        selected_ids.add(index)
        seen_reasons.add(reason)
        if len(selected) >= max_items:
            return selected
    for index, row in enumerate(sorted_rows):
        if index in selected_ids:
            continue
        selected.append(row)
        if len(selected) >= max_items:
            break
    return selected


def rejection_reason_counts(rows: Any) -> dict[str, int]:
    counter = Counter(row["rejection_reason"] for row in annotate_rejected_noise_rows(rows) if row.get("rejection_reason"))
    return dict(sorted(counter.items(), key=lambda item: (rejection_reason_priority(item[0]), item[0])))
