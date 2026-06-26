from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

CALIBRATION_WEIGHT_KEYS = (
    "intensity",
    "frequency",
    "wtp",
    "buyer_authority",
    "current_workaround",
    "incumbent_failure",
    "urgency",
    "evidence_quality",
    "recency",
)

DEFAULT_RECOMMENDED_WEIGHTS: dict[str, float] = {
    "intensity": 0.18,
    "frequency": 0.14,
    "wtp": 0.14,
    "buyer_authority": 0.12,
    "current_workaround": 0.10,
    "incumbent_failure": 0.10,
    "urgency": 0.08,
    "evidence_quality": 0.08,
    "recency": 0.06,
}


def score_prediction(prediction: dict[str, Any], weights: dict[str, float] | None = None) -> float:
    normalized_weights = weights or DEFAULT_RECOMMENDED_WEIGHTS
    components = _score_components(prediction)
    factors = components.get("factors") if isinstance(components.get("factors"), dict) else {}
    penalties = components.get("penalties") if isinstance(components.get("penalties"), dict) else {}
    weighted_sum = 0.0
    for key in CALIBRATION_WEIGHT_KEYS:
        weighted_sum += _unit_float(factors.get(key)) * float(normalized_weights.get(key, 0.0) or 0.0)
    penalty_sum = sum(_unit_float(value) for value in penalties.values())
    return round(max(0.0, min(100.0, (weighted_sum - penalty_sum) * 100.0)), 4)


def calibrate_from_files(
    *,
    labels_path: str | Path,
    predictions_path: str | Path,
    output_path: str | Path,
    top_n: int = 10,
) -> dict[str, Any]:
    labels = _read_jsonl(labels_path)
    predictions = _read_jsonl(predictions_path)
    labels_by_id = {str(row.get("post_id") or ""): row for row in labels if row.get("post_id") is not None}
    joined = []
    for prediction in predictions:
        post_id = str(prediction.get("post_id") or "")
        label = labels_by_id.get(post_id)
        if label is not None:
            joined.append((score_prediction(prediction), prediction, label))
    joined.sort(key=lambda item: (-item[0], str(item[1].get("post_id") or "")))
    top_rows = joined[: max(0, int(top_n))]
    useful_count = sum(1 for _, _, label in top_rows if bool(label.get("feedback_useful")))
    monetizable_count = sum(1 for _, _, label in top_rows if bool(label.get("is_monetizable")))
    exact_evidence_expected = sum(
        1
        for _, _, label in top_rows
        if str(label.get("evidence_quality") or "").strip().lower() in {"exact_quote", "multi_quote", "linked_multi_source"}
    )
    exact_evidence_count = sum(
        1
        for _, prediction, label in top_rows
        if int(_score_components(prediction).get("exact_evidence_count") or 0) > 0
        and str(label.get("evidence_quality") or "").strip().lower() in {"exact_quote", "multi_quote", "linked_multi_source"}
    )
    artifact = {
        "schema_version": "score_calibration_v1",
        "auto_apply": False,
        "note": "Deterministic recommendation artifact only; do not auto-apply weights without review and regression validation.",
        "labels_path": str(labels_path),
        "predictions_path": str(predictions_path),
        "top_n": int(top_n),
        "matched_prediction_count": len(labels_by_id.keys() & {str(row.get("post_id") or "") for row in predictions}),
        "recommended_weights": dict(DEFAULT_RECOMMENDED_WEIGHTS),
        "metric_summary": {
            "top_n_useful_rate": _rate(useful_count, len(top_rows)),
            "monetizable_precision": _rate(monetizable_count, len(top_rows)),
            "evidence_exact_match_rate": _rate(exact_evidence_count, exact_evidence_expected),
        },
        "top_ranked_post_ids": [str(prediction.get("post_id") or "") for _, prediction, _ in top_rows],
    }
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(artifact, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return artifact


def _read_jsonl(path: str | Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with Path(path).open("r", encoding="utf-8") as handle:
        for line in handle:
            raw = line.strip()
            if raw:
                parsed = json.loads(raw)
                if isinstance(parsed, dict):
                    rows.append(parsed)
    return rows


def _unit_float(value: Any) -> float:
    if isinstance(value, bool):
        return 0.0
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return 0.0
    if not math.isfinite(numeric):
        return 0.0
    return max(0.0, min(1.0, numeric))


def _score_components(prediction: dict[str, Any]) -> dict[str, Any]:
    raw = prediction.get("score_components")
    if isinstance(raw, dict):
        return raw
    raw_json = prediction.get("score_components_json")
    if isinstance(raw_json, str) and raw_json.strip():
        try:
            parsed = json.loads(raw_json)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _rate(numerator: int, denominator: int) -> float | None:
    if denominator <= 0:
        return None
    return round(numerator / denominator, 4)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Write a deterministic, non-auto-apply score calibration artifact.")
    parser.add_argument("--labels", required=True, dest="labels_path")
    parser.add_argument("--predictions", required=True, dest="predictions_path")
    parser.add_argument("--output", required=True, dest="output_path")
    parser.add_argument("--top-n", type=int, default=10)
    args = parser.parse_args(argv)
    calibrate_from_files(
        labels_path=args.labels_path,
        predictions_path=args.predictions_path,
        output_path=args.output_path,
        top_n=args.top_n,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
