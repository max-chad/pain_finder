from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from eval_harness import (  # noqa: E402
    evaluate_predictions,
    generate_live_predictions,
    labels_from_jsonl,
    load_jsonl,
    posts_from_jsonl,
    reference_now_ts_from_labels,
    write_json,
    write_jsonl,
)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a hand-labeled evaluation for the Reddit pain parser")
    parser.add_argument("--dataset", required=True, help="Path to seed posts JSONL")
    parser.add_argument("--labels", required=True, help="Path to hand labels JSONL")
    parser.add_argument("--predictions-path", help="Path to precomputed predictions JSONL")
    parser.add_argument(
        "--baseline-predictions",
        action="append",
        default=[],
        metavar="NAME=PATH",
        help="Offline baseline prediction JSONL. Repeat to compare named baselines in one run.",
    )
    parser.add_argument("--live", action="store_true", help="Run the configured live classifier stack instead of using precomputed predictions")
    parser.add_argument("--output-dir", required=True, help="Directory for metrics.json and predictions.jsonl artifacts")
    parser.add_argument("--reference-now-ts", type=int, help="Override evaluation reference timestamp")
    parser.add_argument("--current-opportunity-max-age-days", type=int, default=180)
    parser.add_argument("--classifier-mode", help="Optional override for classifier mode when running live")
    parser.add_argument("--disable-dspy", action="store_true", help="Disable DSPy even if enabled in config when running live")
    args = parser.parse_args()
    mode_count = int(bool(args.live)) + int(bool(args.predictions_path)) + int(bool(args.baseline_predictions))
    if mode_count != 1:
        parser.error("Choose exactly one of --live, --predictions-path, or repeated --baseline-predictions")
    return args


def _parse_baseline_prediction_spec(spec: str) -> tuple[str, Path]:
    if "=" not in spec:
        raise ValueError(f"invalid --baseline-predictions value: {spec!r}; expected NAME=PATH")
    name, raw_path = spec.split("=", 1)
    normalized_name = name.strip()
    if not normalized_name or not all(char.isalnum() or char in {"_", "-"} for char in normalized_name):
        raise ValueError(f"invalid baseline name: {name!r}")
    if not raw_path.strip():
        raise ValueError(f"invalid baseline path for {normalized_name!r}")
    return normalized_name, Path(raw_path)


BASELINE_SUMMARY_FIELDS = (
    "pain_precision",
    "pain_recall",
    "pain_f1",
    "monetizable_precision",
    "monetizable_recall",
    "monetizable_f1",
    "stale_leakage_rate",
    "screening_false_negative_count",
    "hard_negative_false_positive_rate",
    "hard_negative_false_positive_count",
    "evidence_coverage_rate",
    "evidence_exact_match_rate",
    "cluster_purity",
    "cost_per_useful_insight",
    "latency_ms_per_prediction",
)


def _baseline_metric_summary(metrics: dict[str, object]) -> dict[str, object]:
    pain = metrics["pain"]
    monetizable = metrics["monetizable"]
    stale_leakage = metrics["stale_leakage"]
    hard_negatives = metrics["hard_negatives"]
    evidence = metrics["evidence"]
    clusters = metrics["clusters"]
    return {
        "pain_precision": pain["precision"],
        "pain_recall": pain["recall"],
        "pain_f1": pain["f1"],
        "monetizable_precision": monetizable["precision"],
        "monetizable_recall": monetizable["recall"],
        "monetizable_f1": monetizable["f1"],
        "stale_leakage_rate": stale_leakage["rate"],
        "screening_false_negative_count": metrics["screening_false_negative_count"],
        "hard_negative_false_positive_rate": hard_negatives["false_positive_rate"],
        "hard_negative_false_positive_count": hard_negatives["false_positive_count"],
        "evidence_coverage_rate": evidence["coverage_rate"],
        "evidence_exact_match_rate": evidence["exact_match_rate"],
        "cluster_purity": clusters["purity"],
        "cost_per_useful_insight": metrics["cost_per_useful_insight"],
        "latency_ms_per_prediction": metrics["latency_ms_per_prediction"],
    }


def _baseline_delta(value: object, reference: object) -> float | None:
    if value is None or reference is None:
        return None
    return round(float(value) - float(reference), 3)


def _baseline_comparison(summary: dict[str, object], reference: dict[str, object]) -> dict[str, object]:
    comparison = {f"{field}_delta": _baseline_delta(summary[field], reference[field]) for field in BASELINE_SUMMARY_FIELDS}
    comparison["screening_false_negative_delta"] = comparison["screening_false_negative_count_delta"]
    comparison["hard_negative_false_positive_delta"] = comparison["hard_negative_false_positive_count_delta"]
    return comparison


def _build_runtime_classifier(*, classifier_mode: str | None = None, disable_dspy: bool = False):
    import config
    from classifier import Classifier
    from dspy_parser import DSPyRedditPainParser
    from openrouter import OpenRouterClient

    openrouter = OpenRouterClient(
        api_key=config.LLM_API_KEY,
        model=config.LLM_MODEL,
        deep_dive_model=config.LLM_DEEP_DIVE_MODEL,
        cluster_model=config.LLM_CLUSTER_MODEL,
        gtm_model=config.LLM_GTM_MODEL,
        pricing_map=config.LLM_MODEL_PRICING,
        provider=config.LLM_PROVIDER,
        api_base=config.LLM_API_BASE,
        reasoning_effort=config.LLM_REASONING_EFFORT,
        temperature=config.LLM_TEMPERATURE,
        max_tokens=config.LLM_MAX_TOKENS,
        primary_max_output_tokens=config.PRIMARY_MAX_OUTPUT_TOKENS,
    )

    dspy_parser = None
    if not disable_dspy and config.DSPY_REDDIT_PARSER_ENABLED and config.DSPY_API_KEY:
        dspy_parser = DSPyRedditPainParser(
            api_key=config.DSPY_API_KEY,
            provider=config.DSPY_PROVIDER,
            model=config.DSPY_MODEL,
            api_base=config.DSPY_API_BASE,
            reasoning_effort=config.DSPY_REASONING_EFFORT,
            temperature=config.DSPY_TEMPERATURE,
            max_tokens=config.DSPY_MAX_TOKENS,
        )

    return Classifier(
        openrouter=openrouter,
        dspy_parser=dspy_parser,
        mode=classifier_mode or config.CLASSIFIER_MODE,
        max_concurrency=config.CLASSIFIER_MAX_CONCURRENCY,
        screen_min_rule_score=config.SCREEN_MIN_RULE_SCORE,
        screen_max_llm_candidates_per_run=config.SCREEN_MAX_LLM_CANDIDATES_PER_RUN,
        semantic_candidate_queries=config.SEMANTIC_CANDIDATE_QUERIES,
    )


async def _run_live_predictions(args: argparse.Namespace, reference_now_ts: int, posts):
    classifier = _build_runtime_classifier(
        classifier_mode=args.classifier_mode,
        disable_dspy=args.disable_dspy,
    )
    return await generate_live_predictions(
        posts=posts,
        classifier=classifier,
        reference_now_ts=reference_now_ts,
        current_opportunity_max_age_days=args.current_opportunity_max_age_days,
    )


def main() -> int:
    args = _parse_args()
    posts = posts_from_jsonl(args.dataset)
    labels = labels_from_jsonl(args.labels)
    reference_now_ts = args.reference_now_ts or reference_now_ts_from_labels(labels)
    if reference_now_ts is None:
        raise SystemExit("reference_now_ts must be provided either via labels or --reference-now-ts")

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    if args.baseline_predictions:
        summary: dict[str, object] = {
            "dataset_size": len(posts),
            "reference_now_ts": int(reference_now_ts),
            "reference_baseline": None,
            "baselines": {},
            "comparisons": {},
        }
        seen_names: set[str] = set()
        reference_baseline_name = ""
        reference_metrics: dict[str, object] | None = None
        for spec in args.baseline_predictions:
            try:
                baseline_name, predictions_path = _parse_baseline_prediction_spec(spec)
            except ValueError as exc:
                raise SystemExit(str(exc)) from exc
            if baseline_name in seen_names:
                raise SystemExit(f"duplicate baseline name: {baseline_name}")
            seen_names.add(baseline_name)
            predictions = load_jsonl(predictions_path)
            metrics = evaluate_predictions(
                posts=posts,
                labels=labels,
                predictions=predictions,
                reference_now_ts=reference_now_ts,
                current_opportunity_max_age_days=args.current_opportunity_max_age_days,
            )
            baseline_dir = output_dir / baseline_name
            write_json(baseline_dir / "metrics.json", metrics)
            write_jsonl(baseline_dir / "predictions.jsonl", predictions)
            metrics_summary = _baseline_metric_summary(metrics)
            if reference_metrics is None:
                reference_baseline_name = baseline_name
                reference_metrics = metrics_summary
                summary["reference_baseline"] = baseline_name
            else:
                summary["comparisons"][f"{baseline_name}_vs_{reference_baseline_name}"] = _baseline_comparison(
                    metrics_summary,
                    reference_metrics,
                )
            summary["baselines"][baseline_name] = {
                "metrics_path": f"{baseline_name}/metrics.json",
                "predictions_path": f"{baseline_name}/predictions.jsonl",
                "metrics": metrics_summary,
                **metrics_summary,
            }
        write_json(output_dir / "baseline_summary.json", summary)
        print(f"baseline_count={len(seen_names)} reference_baseline={reference_baseline_name} output_dir={output_dir}")
        return 0

    if args.live:
        predictions = asyncio.run(_run_live_predictions(args, reference_now_ts, posts))
    else:
        predictions = load_jsonl(args.predictions_path)

    metrics = evaluate_predictions(
        posts=posts,
        labels=labels,
        predictions=predictions,
        reference_now_ts=reference_now_ts,
        current_opportunity_max_age_days=args.current_opportunity_max_age_days,
    )

    write_json(output_dir / "metrics.json", metrics)
    write_jsonl(output_dir / "predictions.jsonl", predictions)

    print(
        "dataset_size={dataset} pain_precision={pain_precision:.3f} monetizable_precision={monetizable_precision:.3f} "
        "stale_leakage_rate={stale_leakage:.3f} evidence_coverage={evidence_coverage:.3f} "
        "evidence_exact_match={evidence_exact_match:.3f}".format(
            dataset=metrics["dataset_size"],
            pain_precision=metrics["pain"]["precision"],
            monetizable_precision=metrics["monetizable"]["precision"],
            stale_leakage=metrics["stale_leakage"]["rate"],
            evidence_coverage=metrics["evidence"]["coverage_rate"],
            evidence_exact_match=metrics["evidence"]["exact_match_rate"],
        )
    )
    return 0


if __name__ == "__main__":
    main()
