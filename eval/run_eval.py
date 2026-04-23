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
    parser.add_argument("--live", action="store_true", help="Run the configured live classifier stack instead of using precomputed predictions")
    parser.add_argument("--output-dir", required=True, help="Directory for metrics.json and predictions.jsonl artifacts")
    parser.add_argument("--reference-now-ts", type=int, help="Override evaluation reference timestamp")
    parser.add_argument("--current-opportunity-max-age-days", type=int, default=180)
    parser.add_argument("--classifier-mode", help="Optional override for classifier mode when running live")
    parser.add_argument("--disable-dspy", action="store_true", help="Disable DSPy even if enabled in config when running live")
    args = parser.parse_args()
    if args.live == bool(args.predictions_path):
        parser.error("Choose exactly one of --live or --predictions-path")
    return args


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

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "metrics.json", metrics)
    write_jsonl(output_dir / "predictions.jsonl", predictions)

    print(
        "dataset_size={dataset} pain_precision={pain_precision:.3f} monetizable_precision={monetizable_precision:.3f} "
        "stale_leakage_rate={stale_leakage:.3f}".format(
            dataset=metrics["dataset_size"],
            pain_precision=metrics["pain"]["precision"],
            monetizable_precision=metrics["monetizable"]["precision"],
            stale_leakage=metrics["stale_leakage"]["rate"],
        )
    )
    return 0


if __name__ == "__main__":
    main()
