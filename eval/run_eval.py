from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from eval_harness import (  # noqa: E402
    MVP_MIN_DATASET_SIZE,
    assess_mvp_thresholds,
    build_eval_run_manifest,
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
    parser.add_argument(
        "--mvp-min-dataset-size",
        type=int,
        default=MVP_MIN_DATASET_SIZE,
        help="Optional stricter expanded-benchmark size gate for mvp_thresholds.json; values below 100 do not lower the default gate.",
    )
    parser.add_argument(
        "--waive-mvp-benchmark-size",
        action="store_true",
        help="Explicitly waive the expanded-benchmark size gate in mvp_thresholds.json.",
    )
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
    "top_10_useful_rate",
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
    top_n_useful_rate = metrics.get("top_n_useful_rate") or {}
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
        "top_10_useful_rate": top_n_useful_rate.get("top_10"),
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


def _write_mvp_thresholds(output_dir: Path, metrics: dict[str, object], args: argparse.Namespace) -> dict[str, object]:
    assessment = assess_mvp_thresholds(
        metrics,
        minimum_dataset_size=args.mvp_min_dataset_size,
        waive_expanded_benchmark=args.waive_mvp_benchmark_size,
    )
    write_json(output_dir / "mvp_thresholds.json", assessment)
    return assessment


def _write_run_manifest(
    output_dir: Path,
    *,
    run_mode: str,
    args: argparse.Namespace,
    reference_now_ts: int,
    metrics: dict[str, object],
    mvp_thresholds: dict[str, object],
    artifacts: dict[str, str | Path],
    baselines: dict[str, object] | None = None,
) -> dict[str, object]:
    manifest = build_eval_run_manifest(
        run_mode=run_mode,
        dataset_path=args.dataset,
        labels_path=args.labels,
        output_dir=output_dir,
        reference_now_ts=reference_now_ts,
        metrics=metrics,
        mvp_thresholds=mvp_thresholds,
        artifacts=artifacts,
        baselines=baselines,
    )
    write_json(output_dir / "run_manifest.json", manifest)
    return manifest


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
        reference_mvp_thresholds: dict[str, object] | None = None
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
            mvp_thresholds = _write_mvp_thresholds(baseline_dir, metrics, args)
            write_jsonl(baseline_dir / "predictions.jsonl", predictions)
            metrics_summary = _baseline_metric_summary(metrics)
            if reference_metrics is None:
                reference_baseline_name = baseline_name
                reference_metrics = metrics_summary
                reference_mvp_thresholds = mvp_thresholds
                summary["reference_baseline"] = baseline_name
            else:
                summary["comparisons"][f"{baseline_name}_vs_{reference_baseline_name}"] = _baseline_comparison(
                    metrics_summary,
                    reference_metrics,
                )
            summary["baselines"][baseline_name] = {
                "metrics_path": f"{baseline_name}/metrics.json",
                "predictions_path": f"{baseline_name}/predictions.jsonl",
                "mvp_thresholds_path": f"{baseline_name}/mvp_thresholds.json",
                "mvp_release_decision": mvp_thresholds["release_decision"],
                "mvp_usable": mvp_thresholds["usable_for_mvp"],
                "metrics": metrics_summary,
                **metrics_summary,
            }
        write_json(output_dir / "baseline_summary.json", summary)
        _write_run_manifest(
            output_dir,
            run_mode="baseline_comparison",
            args=args,
            reference_now_ts=reference_now_ts,
            metrics={"dataset_size": len(posts), "reference_now_ts": int(reference_now_ts)},
            mvp_thresholds=reference_mvp_thresholds or {},
            artifacts={"baseline_summary_path": output_dir / "baseline_summary.json"},
            baselines=summary["baselines"],
        )
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
    mvp_thresholds = _write_mvp_thresholds(output_dir, metrics, args)
    write_jsonl(output_dir / "predictions.jsonl", predictions)
    manifest_artifacts: dict[str, str | Path] = {
        "metrics_path": output_dir / "metrics.json",
        "predictions_path": output_dir / "predictions.jsonl",
        "mvp_thresholds_path": output_dir / "mvp_thresholds.json",
    }
    if args.predictions_path:
        manifest_artifacts["input_predictions_path"] = args.predictions_path
    _write_run_manifest(
        output_dir,
        run_mode="live" if args.live else "offline_predictions",
        args=args,
        reference_now_ts=reference_now_ts,
        metrics=metrics,
        mvp_thresholds=mvp_thresholds,
        artifacts=manifest_artifacts,
    )

    print(
        "dataset_size={dataset} pain_precision={pain_precision:.3f} monetizable_precision={monetizable_precision:.3f} "
        "stale_leakage_rate={stale_leakage:.3f} evidence_coverage={evidence_coverage:.3f} "
        "evidence_exact_match={evidence_exact_match:.3f} mvp_release_decision={mvp_release_decision}".format(
            dataset=metrics["dataset_size"],
            pain_precision=metrics["pain"]["precision"],
            monetizable_precision=metrics["monetizable"]["precision"],
            stale_leakage=metrics["stale_leakage"]["rate"],
            evidence_coverage=metrics["evidence"]["coverage_rate"],
            evidence_exact_match=metrics["evidence"]["exact_match_rate"],
            mvp_release_decision=mvp_thresholds["release_decision"],
        )
    )
    return 0


if __name__ == "__main__":
    main()
