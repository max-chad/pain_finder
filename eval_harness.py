from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from classifier import PainSignal
from rejected_noise import HARD_NEGATIVE_TYPES, normalize_rejection_reason
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
VALID_EVIDENCE_QUALITY = {"none", "unverified", "fuzzy_quote", "exact_quote", "multi_quote"}


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


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
    hard_negative_type = normalize_rejection_reason(row.get("hard_negative_type"))
    if hard_negative_type and hard_negative_type not in HARD_NEGATIVE_TYPES:
        raise ValueError(f"invalid hard_negative_type: {row.get('hard_negative_type')!r}")
    evidence_quality = str(row.get("evidence_quality") or "none").strip().lower()
    if evidence_quality not in VALID_EVIDENCE_QUALITY:
        raise ValueError(f"invalid evidence_quality: {row.get('evidence_quality')!r}")
    return {
        "post_id": str(row["post_id"]),
        "is_pain": _require_label_bool(row.get("is_pain"), field_name="is_pain"),
        "is_monetizable": _require_label_bool(row.get("is_monetizable"), field_name="is_monetizable"),
        "post_type": _require_label_choice(row.get("post_type"), field_name="post_type", allowed=VALID_POST_TYPES - {"unclassified"}),
        "is_current_opportunity": _require_label_bool(row.get("is_current_opportunity"), field_name="is_current_opportunity"),
        "first_handness": _require_label_choice(row.get("first_handness"), field_name="first_handness", allowed=VALID_FIRST_HANDNESS),
        "buyer_authority": _require_label_choice(row.get("buyer_authority"), field_name="buyer_authority", allowed=VALID_BUYER_AUTHORITY),
        "reference_now_ts": _parse_optional_reference_now_ts(row.get("reference_now_ts")),
        "hard_negative_type": hard_negative_type,
        "evidence_quality": evidence_quality,
        "feedback_useful": _safe_bool(row.get("feedback_useful")),
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
        "hard_negative_type": "",
        "verified_evidence_count": 0,
        "exact_evidence_count": 0,
    }


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
            "hard_negative_type": "",
            "verified_evidence_count": 0,
            "exact_evidence_count": 0,
        }
    analysis_payload = signal.analysis_payload if isinstance(signal.analysis_payload, dict) else {}
    score_components = signal.score_components if isinstance(signal.score_components, dict) else {}
    hard_negative_type = normalize_rejection_reason(
        analysis_payload.get("hard_negative_type") or score_components.get("hard_negative_type")
    )

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
        "hard_negative_type": hard_negative_type,
        "verified_evidence_count": _safe_int(score_components.get("verified_evidence_count"), default=0),
        "exact_evidence_count": _safe_int(score_components.get("exact_evidence_count"), default=0),
        "category": str(signal.category or ""),
        "summary": str(signal.summary or ""),
        "pain_level": _safe_int(signal.pain_level, default=0),
        "willingness_to_pay": _safe_int(signal.willingness_to_pay, default=0),
        "niche_category": str(signal.niche_category or ""),
        "competitor_tags": [str(tag) for tag in signal.competitor_tags or []],
    }


async def generate_live_predictions(
    *,
    posts: list[Post],
    classifier: Any,
    reference_now_ts: int,
    current_opportunity_max_age_days: int = 180,
) -> list[dict[str, Any]]:
    signals = await classifier.classify_batch(posts)
    signal_by_post_id = {signal.post.post_id: signal for signal in signals}
    screen_min_rule_score = max(0, _safe_int(getattr(classifier, "screen_min_rule_score", 0), default=0))

    predictions: list[dict[str, Any]] = []
    for post in posts:
        prescreen_score = _safe_int(classifier.prescreen_score(post), default=0)
        signal = signal_by_post_id.get(post.post_id)
        if prescreen_score < screen_min_rule_score:
            status = "screened_out"
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
    hard_negative_candidate_count = 0
    hard_negative_false_positive_count = 0
    exact_evidence_expected_count = 0
    exact_evidence_match_count = 0

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
        predicted_hard_negative_type = normalize_rejection_reason(prediction.get("hard_negative_type"))
        predicted_exact_evidence_count = _safe_int(prediction.get("exact_evidence_count"), default=0)

        label_is_pain = bool(label["is_pain"])
        label_is_monetizable = bool(label["is_monetizable"])
        label_is_current = bool(label["is_current_opportunity"])
        label_hard_negative_type = str(label.get("hard_negative_type") or "")
        label_evidence_quality = str(label.get("evidence_quality") or "none")

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

        if not label_is_current:
            stale_candidate_count += 1
            if predicted_bucket == "current_opportunity":
                stale_leakage_count += 1

        if label_is_pain and prediction_status == "screened_out":
            screening_false_negative_post_ids.append(post_id)

        if label_hard_negative_type:
            hard_negative_candidate_count += 1
            if (
                predicted_is_monetizable
                or (predicted_is_pain and not predicted_hard_negative_type)
                or (predicted_hard_negative_type and predicted_hard_negative_type != label_hard_negative_type)
            ):
                hard_negative_false_positive_count += 1

        if label_evidence_quality in {"exact_quote", "multi_quote"}:
            exact_evidence_expected_count += 1
            if predicted_exact_evidence_count > 0:
                exact_evidence_match_count += 1

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
        "hard_negative_false_positive": {
            "count": hard_negative_false_positive_count,
            "candidate_count": hard_negative_candidate_count,
            "rate": round(hard_negative_false_positive_count / hard_negative_candidate_count, 3)
            if hard_negative_candidate_count
            else 0.0,
        },
        "verified_evidence": {
            "exact_match_count": exact_evidence_match_count,
            "expected_count": exact_evidence_expected_count,
            "exact_match_rate": round(exact_evidence_match_count / exact_evidence_expected_count, 3)
            if exact_evidence_expected_count
            else 0.0,
        },
        "post_type_confusion": ordered_confusion,
        "first_handness_accuracy": round(first_handness_matches / evaluated_count, 3) if evaluated_count else 0.0,
        "buyer_authority_accuracy": round(buyer_authority_matches / evaluated_count, 3) if evaluated_count else 0.0,
    }
