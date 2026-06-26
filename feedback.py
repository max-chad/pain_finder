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
    "too_generic": {"feedback_useful": False, "hard_negative_type": "generic_question"},
    "wrong_segment": {"feedback_useful": False, "hard_negative_type": "out_of_scope"},
    "bad_evidence": {"feedback_useful": False, "evidence_relevance": "irrelevant"},
}


def normalize_feedback_value(value: Any) -> str:
    normalized = str(value or "").strip().lower()
    if normalized not in FEEDBACK_VALUE_SET:
        raise ValueError(f"Unsupported feedback_value: {value!r}")
    return normalized


def empty_feedback_summary() -> dict[str, int]:
    return {value: 0 for value in FEEDBACK_VALUES}


def encode_feedback_metadata(metadata: dict[str, Any] | None) -> str:
    return json.dumps(metadata or {}, ensure_ascii=False, allow_nan=False)
