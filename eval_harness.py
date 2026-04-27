from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any

from classifier import PainSignal
from feedback import build_feedback_label_review_row
from scraper import Post

VALID_POST_TYPES = {
    "first_person_pain",
    "solution_request",
    "founder_pitch",
    "news_analysis",
    "tool_comparison",
    "advice_thread",
    "vendor_rant",
    "unclassified",
}
VALID_FIRST_HANDNESS = {"first_hand", "second_hand", "aggregated", "speculative", "unknown"}
VALID_BUYER_AUTHORITY = {
    "intern",
    "ic",
    "engineer",
    "manager",
    "head_of_ops",
    "founder_owner",
    "agency_operator",
    "unknown",
}
VALID_EVIDENCE_QUALITY = {"no_quote", "weak_quote", "exact_quote", "multi_quote", "linked_multi_source"}
VALID_PAIN_TYPES = {
    "operational",
    "integration",
    "reporting",
    "billing",
    "support",
    "compliance",
    "security",
    "data_quality",
    "workflow",
    "unknown",
}
VALID_EXPRESSION_TYPES = {
    "first_person_complaint",
    "solution_request",
    "wish",
    "workaround",
    "tool_comparison",
    "vendor_rant",
    "second_hand_report",
    "unknown",
}
VALID_OPPORTUNITY_TYPES = {
    "current_opportunity",
    "evergreen_pain",
    "research_lead",
    "needs_validation",
    "not_opportunity",
    "unknown",
}
VALID_LABEL_STRENGTHS = {"none", "low", "medium", "high"}
VALID_HARD_NEGATIVE_TYPES = {
    "none",
    "generic_recommendation",
    "generic_opinion",
    "b2c_consumer_rant",
    "solved_issue",
    "founder_pitch",
    "news_analysis",
    "vendor_comparison_no_consequence",
    "low_context_complaint",
    "out_of_scope",
}
VALID_EVIDENCE_RELEVANCE = {"relevant", "irrelevant", "not_applicable", "unknown"}
VALID_SOURCE_LINK_VALIDITY = {"valid", "invalid", "not_applicable", "unknown"}


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _safe_float(value: Any, default: float = 0.0) -> float:
    if isinstance(value, bool):
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _coerce_unit_float(value: Any) -> float:
    return round(max(0.0, min(1.0, _safe_float(value))), 3)


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


def _safe_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "y", "on"}:
            return True
        if normalized in {"0", "false", "no", "n", "off", ""}:
            return False
    return bool(value)


def _require_label_bool(value: Any, *, field_name: str) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "y", "on"}:
            return True
        if normalized in {"0", "false", "no", "n", "off"}:
            return False
    raise ValueError(f"invalid {field_name}: {value!r}")


def _normalized_choice(value: Any, *, allowed: set[str], fallback: str) -> str:
    normalized = str(value or "").strip().lower()
    if normalized in allowed:
        return normalized
    return fallback


def _require_label_choice(value: Any, *, field_name: str, allowed: set[str]) -> str:
    normalized = str(value or "").strip().lower()
    if normalized in allowed:
        return normalized
    raise ValueError(f"invalid {field_name}: {value!r}")


def _optional_label_choice(value: Any, *, field_name: str, allowed: set[str]) -> str | None:
    if value in {None, ""}:
        return None
    return _require_label_choice(value, field_name=field_name, allowed=allowed)


def _require_label_text(row: dict[str, Any], field_name: str) -> str:
    if field_name not in row:
        raise ValueError(f"label row is missing {field_name}")
    value = row[field_name]
    if value is None:
        raise ValueError(f"invalid {field_name}: {value!r}")
    return str(value).strip()


def _optional_label_bool(value: Any, *, field_name: str) -> bool | None:
    if value in {None, ""}:
        return None
    return _require_label_bool(value, field_name=field_name)


def _parse_optional_reference_now_ts(value: Any) -> int | None:
    if value in {None, ""}:
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"invalid reference_now_ts: {value!r}") from exc
    if parsed <= 0:
        raise ValueError(f"invalid reference_now_ts: {value!r}")
    return parsed


def _ensure_unique_post_ids(post_ids: list[str], *, duplicate_message: str) -> None:
    seen: set[str] = set()
    for post_id in post_ids:
        if post_id in seen:
            raise ValueError(f"{duplicate_message}: {post_id}")
        seen.add(post_id)


def load_jsonl(path: str | Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with Path(path).open("r", encoding="utf-8") as handle:
        for line in handle:
            raw = line.strip()
            if not raw:
                continue
            rows.append(json.loads(raw))
    return rows


def write_json(path: str | Path, payload: dict[str, Any]) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_jsonl(path: str | Path, rows: list[dict[str, Any]]) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True) + "\n")


def feedback_events_to_label_review_rows(
    feedback_rows: list[dict[str, Any]],
    *,
    pain_points_by_id: dict[str, dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    pain_points_by_id = pain_points_by_id or {}
    rows: list[dict[str, Any]] = []
    for feedback_row in feedback_rows:
        post_id = str(feedback_row.get("post_id") or "")
        rows.append(build_feedback_label_review_row(feedback_row, pain_point=pain_points_by_id.get(post_id)))
    return rows


def write_feedback_label_review_jsonl(
    path: str | Path,
    feedback_rows: list[dict[str, Any]],
    *,
    pain_points_by_id: dict[str, dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    rows = feedback_events_to_label_review_rows(feedback_rows, pain_points_by_id=pain_points_by_id)
    write_jsonl(path, rows)
    return rows


def posts_from_jsonl(path: str | Path) -> list[Post]:
    posts: list[Post] = []
    for row in load_jsonl(path):
        posts.append(
            Post(
                post_id=str(row["post_id"]),
                subreddit=str(row.get("subreddit", "unknown")),
                title=str(row.get("title", "")),
                body=str(row.get("body", "")),
                url=str(row.get("url", "")),
                score=_safe_int(row.get("score", 0)),
                permalink=str(row.get("permalink", "")),
                top_comments=[str(comment) for comment in row.get("top_comments", []) if str(comment).strip()],
                source=str(row.get("source", "reddit") or "reddit"),
                discovery_query=str(row.get("discovery_query", "")),
                source_created_at=(str(row.get("source_created_at")) if row.get("source_created_at") else None),
                source_created_ts=(_safe_int(row.get("source_created_ts"), default=0) or None),
                author_name=(str(row.get("author_name")) if row.get("author_name") else None),
            )
        )
    return posts


def _normalize_label_row(row: dict[str, Any]) -> dict[str, Any]:
    if not row.get("post_id"):
        raise ValueError("label row is missing post_id")
    evidence_quality = _require_label_choice(
        row.get("evidence_quality"),
        field_name="evidence_quality",
        allowed=VALID_EVIDENCE_QUALITY,
    )
    evidence_expected = (
        evidence_quality != "no_quote"
        if row.get("evidence_expected") is None
        else _require_label_bool(row.get("evidence_expected"), field_name="evidence_expected")
    )
    return {
        "post_id": str(row["post_id"]),
        "is_pain": _require_label_bool(row.get("is_pain"), field_name="is_pain"),
        "is_monetizable": _require_label_bool(row.get("is_monetizable"), field_name="is_monetizable"),
        "post_type": _require_label_choice(row.get("post_type"), field_name="post_type", allowed=VALID_POST_TYPES - {"unclassified"}),
        "pain_type": _require_label_choice(row.get("pain_type"), field_name="pain_type", allowed=VALID_PAIN_TYPES),
        "expression_type": _require_label_choice(
            row.get("expression_type"),
            field_name="expression_type",
            allowed=VALID_EXPRESSION_TYPES,
        ),
        "first_handness": _require_label_choice(row.get("first_handness"), field_name="first_handness", allowed=VALID_FIRST_HANDNESS),
        "buyer_authority": _require_label_choice(row.get("buyer_authority"), field_name="buyer_authority", allowed=VALID_BUYER_AUTHORITY),
        "intensity_label": _require_label_choice(row.get("intensity_label"), field_name="intensity_label", allowed=VALID_LABEL_STRENGTHS),
        "urgency_label": _require_label_choice(row.get("urgency_label"), field_name="urgency_label", allowed=VALID_LABEL_STRENGTHS),
        "wtp_label": _require_label_choice(row.get("wtp_label"), field_name="wtp_label", allowed=VALID_LABEL_STRENGTHS),
        "current_workaround": _require_label_text(row, "current_workaround"),
        "incumbent_failure": _require_label_text(row, "incumbent_failure"),
        "evidence_quality": evidence_quality,
        "evidence_expected": evidence_expected,
        "opportunity_type": _require_label_choice(
            row.get("opportunity_type"),
            field_name="opportunity_type",
            allowed=VALID_OPPORTUNITY_TYPES,
        ),
        "is_current_opportunity": _require_label_bool(row.get("is_current_opportunity"), field_name="is_current_opportunity"),
        "hard_negative_type": _require_label_choice(
            row.get("hard_negative_type"),
            field_name="hard_negative_type",
            allowed=VALID_HARD_NEGATIVE_TYPES,
        ),
        "expected_cluster_key": str(row.get("expected_cluster_key") or "").strip(),
        "evidence_relevance": _optional_label_choice(
            row.get("evidence_relevance"),
            field_name="evidence_relevance",
            allowed=VALID_EVIDENCE_RELEVANCE,
        ),
        "source_link_validity": _optional_label_choice(
            row.get("source_link_validity"),
            field_name="source_link_validity",
            allowed=VALID_SOURCE_LINK_VALIDITY,
        ),
        "feedback_useful": _optional_label_bool(row.get("feedback_useful"), field_name="feedback_useful"),
        "reference_now_ts": _parse_optional_reference_now_ts(row.get("reference_now_ts")),
        "notes": str(row.get("notes", "")),
    }


def labels_from_jsonl(path: str | Path) -> list[dict[str, Any]]:
    return [_normalize_label_row(row) for row in load_jsonl(path)]


def reference_now_ts_from_labels(labels: list[dict[str, Any]], fallback: int | None = None) -> int | None:
    timestamps = {
        parsed
        for parsed in (_parse_optional_reference_now_ts(label.get("reference_now_ts")) for label in labels)
        if parsed is not None
    }
    if len(timestamps) > 1:
        raise ValueError("labels contain multiple reference_now_ts values")
    if timestamps:
        return next(iter(timestamps))
    return fallback


def classify_opportunity_bucket(
    post: Post,
    *,
    current_opportunity_max_age_days: int = 180,
    reference_now_ts: int | None = None,
) -> str:
    if not post.source_created_ts:
        return "unknown_age"
    if reference_now_ts is None:
        raise ValueError("reference_now_ts is required for deterministic opportunity bucketing")
    age_seconds = max(0, int(reference_now_ts) - int(post.source_created_ts))
    age_days = age_seconds / 86400.0
    if age_days <= max(1, int(current_opportunity_max_age_days)):
        return "current_opportunity"
    return "evergreen_pain"


def _default_prediction(post: Post, *, reference_now_ts: int, current_opportunity_max_age_days: int) -> dict[str, Any]:
    return {
        "post_id": post.post_id,
        "prediction_status": "missing",
        "prescreen_score": 0,
        "is_pain": False,
        "is_monetizable": False,
        "post_type": "unclassified",
        "first_handness": "unknown",
        "buyer_authority": "unknown",
        "opportunity_bucket": classify_opportunity_bucket(
            post,
            current_opportunity_max_age_days=current_opportunity_max_age_days,
            reference_now_ts=reference_now_ts,
        ),
        "analysis_mode": "missing",
        "verified_evidence": [],
        "evidence_quality": "no_quote",
        "evidence_match_rate": 0.0,
        "confidence": 0.0,
        "uncertainty_reason": "",
        "needs_human_review": False,
    }


def _verified_evidence_payload(signal: PainSignal) -> list[dict[str, Any]]:
    payload: list[dict[str, Any]] = []
    for item in signal.verified_evidence:
        if is_dataclass(item):
            payload.append(asdict(item))
        elif isinstance(item, dict):
            payload.append(dict(item))
    return payload


def prediction_from_signal(
    post: Post,
    signal: PainSignal | None,
    *,
    prescreen_score: int,
    prediction_status: str,
    reference_now_ts: int,
    current_opportunity_max_age_days: int,
) -> dict[str, Any]:
    bucket = classify_opportunity_bucket(
        post,
        current_opportunity_max_age_days=current_opportunity_max_age_days,
        reference_now_ts=reference_now_ts,
    )
    if signal is None:
        return {
            "post_id": post.post_id,
            "prediction_status": prediction_status,
            "prescreen_score": int(prescreen_score),
            "is_pain": False,
            "is_monetizable": False,
            "post_type": "unclassified",
            "first_handness": "unknown",
            "buyer_authority": "unknown",
            "opportunity_bucket": bucket,
            "analysis_mode": prediction_status,
            "verified_evidence": [],
            "evidence_quality": "no_quote",
            "evidence_match_rate": 0.0,
            "confidence": 0.0,
            "uncertainty_reason": "",
            "needs_human_review": False,
        }

    return {
        "post_id": post.post_id,
        "prediction_status": prediction_status,
        "prescreen_score": int(prescreen_score),
        "is_pain": True,
        "is_monetizable": bool(signal.is_monetizable),
        "post_type": _normalized_choice(signal.post_type, allowed=VALID_POST_TYPES, fallback="unclassified"),
        "first_handness": _normalized_choice(signal.first_handness, allowed=VALID_FIRST_HANDNESS, fallback="unknown"),
        "buyer_authority": _normalized_choice(signal.buyer_authority, allowed=VALID_BUYER_AUTHORITY, fallback="unknown"),
        "opportunity_bucket": bucket,
        "analysis_mode": str(signal.analysis_mode or "classified"),
        "category": str(signal.category or ""),
        "summary": str(signal.summary or ""),
        "pain_level": _safe_int(signal.pain_level, default=0),
        "willingness_to_pay": _safe_int(signal.willingness_to_pay, default=0),
        "niche_category": str(signal.niche_category or ""),
        "competitor_tags": [str(tag) for tag in signal.competitor_tags or []],
        "verified_evidence": _verified_evidence_payload(signal),
        "evidence_quality": _normalized_choice(
            signal.evidence_quality,
            allowed=VALID_EVIDENCE_QUALITY,
            fallback="no_quote",
        ),
        "evidence_match_rate": _coerce_unit_float(signal.evidence_match_rate),
        "confidence": _coerce_unit_float(signal.confidence),
        "uncertainty_reason": str(signal.uncertainty_reason or ""),
        "needs_human_review": bool(signal.needs_human_review),
    }


async def generate_live_predictions(
    *,
    posts: list[Post],
    classifier: Any,
    reference_now_ts: int,
    current_opportunity_max_age_days: int = 180,
) -> list[dict[str, Any]]:
    screen_min_rule_score = max(0, _safe_int(getattr(classifier, "screen_min_rule_score", 0), default=0))
    prescreen_scores = {post.post_id: _safe_int(classifier.prescreen_score(post), default=0) for post in posts}
    if hasattr(classifier, "select_candidates"):
        candidate_posts, _screen_stats = await classifier.select_candidates(posts, max_candidates=None)
    elif hasattr(classifier, "prescreen_posts"):
        candidate_posts, _screen_stats = classifier.prescreen_posts(posts, max_candidates=None)
    else:
        scored = [(prescreen_scores[post.post_id], post) for post in posts if prescreen_scores[post.post_id] >= screen_min_rule_score]
        scored.sort(key=lambda item: item[0], reverse=True)
        candidate_posts = [post for _, post in scored]
        candidate_cap = max(0, _safe_int(getattr(classifier, "screen_max_llm_candidates_per_run", 0), default=0))
        if candidate_cap > 0:
            candidate_posts = candidate_posts[:candidate_cap]

    signals = await classifier.classify_batch(candidate_posts)
    signal_by_post_id = {signal.post.post_id: signal for signal in signals}
    candidate_post_ids = {post.post_id for post in candidate_posts}

    predictions: list[dict[str, Any]] = []
    for post in posts:
        prescreen_score = prescreen_scores.get(post.post_id, 0)
        signal = signal_by_post_id.get(post.post_id)
        if post.post_id not in candidate_post_ids:
            status = "screened_out" if prescreen_score < screen_min_rule_score else "capped_out"
            signal = None
        elif signal is None:
            status = "no_signal"
        else:
            status = "classified"
        predictions.append(
            prediction_from_signal(
                post,
                signal,
                prescreen_score=prescreen_score,
                prediction_status=status,
                reference_now_ts=reference_now_ts,
                current_opportunity_max_age_days=current_opportunity_max_age_days,
            )
        )
    return predictions


def _binary_metrics(*, tp: int, fp: int, fn: int) -> dict[str, Any]:
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0
    return {
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "precision": round(precision, 3),
        "recall": round(recall, 3),
        "f1": round(f1, 3),
    }


def _prediction_verified_evidence(prediction: dict[str, Any]) -> list[dict[str, Any]]:
    raw = prediction.get("verified_evidence")
    if raw is None:
        raw = prediction.get("verified_evidence_json")
    return [item for item in _json_list(raw) if isinstance(item, dict)]


def _prediction_evidence_quality(prediction: dict[str, Any]) -> str:
    return _normalized_choice(
        prediction.get("evidence_quality"),
        allowed=VALID_EVIDENCE_QUALITY,
        fallback="no_quote",
    )


def _has_matched_evidence(prediction: dict[str, Any], *, evidence_quality: str, evidence: list[dict[str, Any]]) -> bool:
    if evidence_quality != "no_quote":
        return True
    if _coerce_unit_float(prediction.get("evidence_match_rate")) > 0:
        return True
    return any(str(item.get("match_type") or "none").lower() in {"exact", "fuzzy"} for item in evidence)


def _has_exact_evidence(*, evidence_quality: str, evidence: list[dict[str, Any]]) -> bool:
    if evidence:
        return any(str(item.get("match_type") or "none").lower() == "exact" for item in evidence)
    return evidence_quality in {"exact_quote", "multi_quote", "linked_multi_source"}


def _prediction_cluster_key(prediction: dict[str, Any]) -> str:
    for field_name in ("cluster_key", "canonical_cluster_key", "cluster_id", "canonical_cluster_id", "cluster"):
        value = prediction.get(field_name)
        if value not in {None, ""}:
            return str(value)
    return ""


def _prediction_score(prediction: dict[str, Any]) -> float | None:
    for field_name in ("opportunity_score", "score", "pain_score"):
        value = prediction.get(field_name)
        if value not in {None, ""}:
            return _safe_float(value)
    return None


def _rate_payload(*, count: int, denominator: int) -> dict[str, Any]:
    return {
        "count": count,
        "candidate_count": denominator,
        "rate": round(count / denominator, 3) if denominator else None,
    }


def evaluate_predictions(
    *,
    posts: list[Post],
    labels: list[dict[str, Any]],
    predictions: list[dict[str, Any]],
    reference_now_ts: int | None = None,
    current_opportunity_max_age_days: int = 180,
) -> dict[str, Any]:
    normalized_labels = [_normalize_label_row(row) for row in labels]
    label_reference_now_ts = reference_now_ts_from_labels(normalized_labels)
    resolved_reference_now_ts = reference_now_ts or label_reference_now_ts
    if resolved_reference_now_ts is None:
        raise ValueError("reference_now_ts is required")

    _ensure_unique_post_ids([post.post_id for post in posts], duplicate_message="duplicate post_id in posts")
    _ensure_unique_post_ids([label["post_id"] for label in normalized_labels], duplicate_message="duplicate label post_id")
    _ensure_unique_post_ids([str(row["post_id"]) for row in predictions if row.get("post_id")], duplicate_message="duplicate prediction post_id")

    posts_by_id = {post.post_id: post for post in posts}
    label_by_post_id = {label["post_id"]: label for label in normalized_labels}
    prediction_by_post_id = {str(row["post_id"]): row for row in predictions if row.get("post_id")}

    pain_tp = pain_fp = pain_fn = 0
    monetizable_tp = monetizable_fp = monetizable_fn = 0
    stale_leakage_count = 0
    stale_candidate_count = 0
    screening_false_negative_post_ids: list[str] = []
    post_type_confusion: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    first_handness_matches = 0
    buyer_authority_matches = 0
    evaluated_count = 0
    prediction_status_counts: dict[str, int] = defaultdict(int)
    evidence_quality_counts: dict[str, int] = defaultdict(int)
    evidence_predicted_pain_count = 0
    evidence_coverage_count = 0
    evidence_exact_match_count = 0
    evidence_needs_review_count = 0
    evidence_match_rate_sum = 0.0
    evidence_confidence_sum = 0.0
    hard_negative_counts: dict[str, dict[str, int]] = defaultdict(lambda: {"count": 0, "false_positive_count": 0})
    hard_negative_total_count = 0
    hard_negative_false_positive_count = 0
    manual_evidence_relevance_counts: dict[str, int] = defaultdict(int)
    manual_source_link_validity_counts: dict[str, int] = defaultdict(int)
    expected_to_predicted_clusters: dict[str, set[str]] = defaultdict(set)
    predicted_cluster_expected_counts: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    cluster_evaluated_count = 0
    feedback_rows: list[tuple[float, bool]] = []
    useful_prediction_count = 0
    total_prediction_cost = 0.0
    cost_observed_count = 0
    latency_values: list[float] = []

    for post_id, label in label_by_post_id.items():
        post = posts_by_id.get(post_id)
        if post is None:
            raise ValueError(f"label references unknown post_id: {post_id}")
        prediction = prediction_by_post_id.get(post_id)
        if prediction is None:
            prediction = _default_prediction(
                post,
                reference_now_ts=resolved_reference_now_ts,
                current_opportunity_max_age_days=current_opportunity_max_age_days,
            )

        prediction_status = str(prediction.get("prediction_status", "missing"))
        prediction_status_counts[prediction_status] += 1
        predicted_is_pain = _safe_bool(prediction.get("is_pain"))
        predicted_is_monetizable = _safe_bool(prediction.get("is_monetizable"))
        predicted_post_type = _normalized_choice(prediction.get("post_type"), allowed=VALID_POST_TYPES, fallback="unclassified")
        predicted_first_handness = _normalized_choice(prediction.get("first_handness"), allowed=VALID_FIRST_HANDNESS, fallback="unknown")
        predicted_buyer_authority = _normalized_choice(prediction.get("buyer_authority"), allowed=VALID_BUYER_AUTHORITY, fallback="unknown")
        predicted_bucket = str(prediction.get("opportunity_bucket") or classify_opportunity_bucket(
            post,
            current_opportunity_max_age_days=current_opportunity_max_age_days,
            reference_now_ts=resolved_reference_now_ts,
        ))
        evidence = _prediction_verified_evidence(prediction)
        evidence_quality = _prediction_evidence_quality(prediction)
        has_matched_evidence = predicted_is_pain and _has_matched_evidence(
            prediction,
            evidence_quality=evidence_quality,
            evidence=evidence,
        )
        has_exact_evidence = predicted_is_pain and _has_exact_evidence(evidence_quality=evidence_quality, evidence=evidence)
        if predicted_is_pain:
            evidence_predicted_pain_count += 1
            evidence_quality_counts[evidence_quality] += 1
            evidence_match_rate_sum += _coerce_unit_float(prediction.get("evidence_match_rate"))
            evidence_confidence_sum += _coerce_unit_float(prediction.get("confidence"))
            if _safe_bool(prediction.get("needs_human_review")):
                evidence_needs_review_count += 1
            if has_matched_evidence:
                evidence_coverage_count += 1
            if has_exact_evidence:
                evidence_exact_match_count += 1

        label_is_pain = bool(label["is_pain"])
        label_is_monetizable = bool(label["is_monetizable"])
        label_is_current = bool(label["is_current_opportunity"])
        hard_negative_type = str(label.get("hard_negative_type") or "none")
        if hard_negative_type != "none":
            hard_negative_counts[hard_negative_type]["count"] += 1
            hard_negative_total_count += 1
            if predicted_is_pain:
                hard_negative_counts[hard_negative_type]["false_positive_count"] += 1
                hard_negative_false_positive_count += 1

        evidence_relevance = label.get("evidence_relevance")
        if has_matched_evidence and evidence_relevance in {"relevant", "irrelevant"}:
            manual_evidence_relevance_counts[str(evidence_relevance)] += 1
        source_link_validity = label.get("source_link_validity")
        if has_matched_evidence and source_link_validity in {"valid", "invalid"}:
            manual_source_link_validity_counts[str(source_link_validity)] += 1

        expected_cluster_key = str(label.get("expected_cluster_key") or "")
        predicted_cluster_key = _prediction_cluster_key(prediction)
        if expected_cluster_key and predicted_cluster_key:
            expected_to_predicted_clusters[expected_cluster_key].add(predicted_cluster_key)
            predicted_cluster_expected_counts[predicted_cluster_key][expected_cluster_key] += 1
            cluster_evaluated_count += 1

        feedback_useful = label.get("feedback_useful")
        if predicted_is_pain and feedback_useful is not None:
            if bool(feedback_useful):
                useful_prediction_count += 1
            prediction_score = _prediction_score(prediction)
            if prediction_score is not None:
                feedback_rows.append((prediction_score, bool(feedback_useful)))
        cost_value = prediction.get("cost_usd")
        if cost_value not in {None, ""}:
            total_prediction_cost += max(0.0, _safe_float(cost_value))
            cost_observed_count += 1
        latency_value = prediction.get("latency_ms")
        if latency_value not in {None, ""}:
            latency_values.append(max(0.0, _safe_float(latency_value)))

        if predicted_is_pain and label_is_pain:
            pain_tp += 1
        elif predicted_is_pain and not label_is_pain:
            pain_fp += 1
        elif (not predicted_is_pain) and label_is_pain:
            pain_fn += 1

        if predicted_is_monetizable and label_is_monetizable:
            monetizable_tp += 1
        elif predicted_is_monetizable and not label_is_monetizable:
            monetizable_fp += 1
        elif (not predicted_is_monetizable) and label_is_monetizable:
            monetizable_fn += 1

        if label_is_pain and not label_is_current:
            stale_candidate_count += 1
            if predicted_is_pain and predicted_bucket == "current_opportunity":
                stale_leakage_count += 1

        if label_is_pain and prediction_status == "screened_out":
            screening_false_negative_post_ids.append(post_id)

        post_type_confusion[label["post_type"]][predicted_post_type] += 1
        evaluated_count += 1
        if predicted_first_handness == label["first_handness"]:
            first_handness_matches += 1
        if predicted_buyer_authority == label["buyer_authority"]:
            buyer_authority_matches += 1

    ordered_confusion = {
        actual: {predicted: counts[predicted] for predicted in sorted(counts)}
        for actual, counts in sorted(post_type_confusion.items())
    }
    ordered_status_counts = {status: prediction_status_counts[status] for status in sorted(prediction_status_counts)}
    ordered_evidence_quality_counts = {quality: evidence_quality_counts[quality] for quality in sorted(evidence_quality_counts)}
    evidence_denominator = evidence_predicted_pain_count or 1
    ordered_hard_negative_counts = {
        hard_type: {
            "count": counts["count"],
            "false_positive_count": counts["false_positive_count"],
            "false_positive_rate": round(counts["false_positive_count"] / counts["count"], 3) if counts["count"] else None,
        }
        for hard_type, counts in sorted(hard_negative_counts.items())
    }
    manual_relevance_total = manual_evidence_relevance_counts["relevant"] + manual_evidence_relevance_counts["irrelevant"]
    source_validity_total = manual_source_link_validity_counts["valid"] + manual_source_link_validity_counts["invalid"]
    cluster_duplicate_count = sum(max(0, len(predicted_keys) - 1) for predicted_keys in expected_to_predicted_clusters.values())
    predicted_cluster_total = sum(sum(counts.values()) for counts in predicted_cluster_expected_counts.values())
    predicted_cluster_majority_total = sum(max(counts.values()) for counts in predicted_cluster_expected_counts.values() if counts)
    feedback_rows.sort(key=lambda row: row[0], reverse=True)
    top_n_useful_rate = {
        f"top_{n}": round(sum(1 for _, useful in feedback_rows[:n] if useful) / min(n, len(feedback_rows)), 3)
        if feedback_rows
        else None
        for n in (1, 3, 5)
    }
    useful_insight_count = useful_prediction_count

    return {
        "dataset_size": len(label_by_post_id),
        "reference_now_ts": int(resolved_reference_now_ts),
        "prediction_status_counts": ordered_status_counts,
        "pain": _binary_metrics(tp=pain_tp, fp=pain_fp, fn=pain_fn),
        "monetizable": _binary_metrics(tp=monetizable_tp, fp=monetizable_fp, fn=monetizable_fn),
        "stale_leakage": {
            "count": stale_leakage_count,
            "candidate_count": stale_candidate_count,
            "rate": round(stale_leakage_count / stale_candidate_count, 3) if stale_candidate_count else 0.0,
        },
        "screening_false_negative_count": len(screening_false_negative_post_ids),
        "screening_false_negative_post_ids": screening_false_negative_post_ids,
        "post_type_confusion": ordered_confusion,
        "first_handness_accuracy": round(first_handness_matches / evaluated_count, 3) if evaluated_count else 0.0,
        "buyer_authority_accuracy": round(buyer_authority_matches / evaluated_count, 3) if evaluated_count else 0.0,
        "evidence_coverage": round(evidence_coverage_count / evidence_denominator, 3),
        "evidence_exact_match_rate": round(evidence_exact_match_count / evidence_denominator, 3),
        "evidence": {
            "predicted_pain_count": evidence_predicted_pain_count,
            "coverage_count": evidence_coverage_count,
            "coverage_rate": round(evidence_coverage_count / evidence_denominator, 3),
            "exact_match_count": evidence_exact_match_count,
            "exact_match_rate": round(evidence_exact_match_count / evidence_denominator, 3),
            "needs_human_review_count": evidence_needs_review_count,
            "needs_human_review_rate": round(evidence_needs_review_count / evidence_denominator, 3),
            "avg_match_rate": round(evidence_match_rate_sum / evidence_denominator, 3),
            "avg_confidence": round(evidence_confidence_sum / evidence_denominator, 3),
            "quality_counts": ordered_evidence_quality_counts,
            "manual_relevance": {
                "evaluated_count": manual_relevance_total,
                "relevant_count": manual_evidence_relevance_counts["relevant"],
                "irrelevant_count": manual_evidence_relevance_counts["irrelevant"],
                "relevant_rate": round(manual_evidence_relevance_counts["relevant"] / manual_relevance_total, 3)
                if manual_relevance_total
                else None,
            },
            "source_link_validity": {
                "evaluated_count": source_validity_total,
                "valid_count": manual_source_link_validity_counts["valid"],
                "invalid_count": manual_source_link_validity_counts["invalid"],
                "valid_rate": round(manual_source_link_validity_counts["valid"] / source_validity_total, 3)
                if source_validity_total
                else None,
            },
        },
        "hard_negatives": {
            "total_count": hard_negative_total_count,
            "false_positive_count": hard_negative_false_positive_count,
            "false_positive_rate": round(hard_negative_false_positive_count / hard_negative_total_count, 3)
            if hard_negative_total_count
            else None,
            "by_type": ordered_hard_negative_counts,
        },
        "clusters": {
            "evaluated_count": cluster_evaluated_count,
            "duplicate_count": cluster_duplicate_count,
            "duplicate_rate": round(cluster_duplicate_count / cluster_evaluated_count, 3) if cluster_evaluated_count else None,
            "purity": round(predicted_cluster_majority_total / predicted_cluster_total, 3) if predicted_cluster_total else None,
        },
        "top_n_useful_rate": top_n_useful_rate,
        "cost_per_useful_insight": round(total_prediction_cost / useful_insight_count, 3) if useful_insight_count and cost_observed_count else None,
        "latency_ms_per_prediction": round(sum(latency_values) / len(latency_values), 3) if latency_values else None,
    }
