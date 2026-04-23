# Evaluation harness

This directory is the reproducible scorecard for the Reddit pain parser.

## What is in here
- `seed_posts.jsonl` — small checked-in starter dataset of Reddit-like posts.
- `labels.jsonl` — hand labels for the seed set.
- `labels.schema.json` — label shape and allowed taxonomy values.
- `run_eval.py` — CLI for evaluating either:
  - live classifier output from the configured runtime, or
  - a saved predictions file.

## Why this exists
The parser has already grown more opinionated:
- source-age buckets,
- typed post taxonomy,
- cheap screening,
- composite scoring,
- comment signals,
- canonical clusters.

Without a labeled eval set, every parser change turns into vibe-based debate. This harness makes the next iterations measurable.

## Seed-set caveat
The checked-in seed set is intentionally small and cheap. It is a **starter set**, not a final benchmark.

Target direction:
- grow toward 100-150 labeled posts,
- keep subreddit/domain diversity,
- expand hard negatives (founder pitches, news, generic advice, B2C noise),
- refresh labels when taxonomy changes.

## Label fields
Each `labels.jsonl` row records:
- `is_pain`
- `is_monetizable`
- `post_type`
- `is_current_opportunity`
- `first_handness`
- `buyer_authority`
- `reference_now_ts`
- optional `notes`

`reference_now_ts` is important: it freezes the freshness boundary so `current_opportunity` vs `evergreen_pain` stays deterministic over time.

Current checked-in seed labels use:
- `reference_now_ts = 1776729600`
- which corresponds to `2026-04-21T00:00:00Z`

## Metrics reported
- `pain`: precision / recall / f1
- `monetizable`: precision / recall / f1
- `stale_leakage.rate`
- `screening_false_negative_count`
- `post_type_confusion`
- `first_handness_accuracy`
- `buyer_authority_accuracy`

## Run against live Codex / DSPy stack
This uses the same runtime defaults as the app. If your env already points at Codex + DSPy, the harness will use that.

Example:

```bash
python eval/run_eval.py \
  --dataset eval/seed_posts.jsonl \
  --labels eval/labels.jsonl \
  --live \
  --output-dir eval/artifacts/seed-live \
  --reference-now-ts 1776729600
```

To force the current preferred stack explicitly:

```bash
export LLM_PROVIDER=codex
export LLM_MODEL=gpt-5.3-spark
export LLM_REASONING_EFFORT=high
export DSPY_PROVIDER=codex
export DSPY_MODEL=gpt-5.3-spark
export DSPY_REASONING_EFFORT=high
python eval/run_eval.py \
  --dataset eval/seed_posts.jsonl \
  --labels eval/labels.jsonl \
  --live \
  --output-dir eval/artifacts/seed-live \
  --reference-now-ts 1776729600
```

If you want to compare without DSPy:

```bash
python eval/run_eval.py \
  --dataset eval/seed_posts.jsonl \
  --labels eval/labels.jsonl \
  --live \
  --disable-dspy \
  --output-dir eval/artifacts/seed-openrouter \
  --reference-now-ts 1776729600
```

## Run against a saved predictions file
Useful when you already captured predictions and want deterministic re-scoring.

```bash
python eval/run_eval.py \
  --dataset eval/seed_posts.jsonl \
  --labels eval/labels.jsonl \
  --predictions-path eval/artifacts/seed-live/predictions.jsonl \
  --output-dir eval/artifacts/seed-rescore \
  --reference-now-ts 1776729600
```

## Artifact layout
Each run writes:
- `metrics.json`
- `predictions.jsonl`

inside the `--output-dir` you pass.

## Labeling guidance
Prefer these rules when expanding the set:
- `is_pain=true` only when there is a concrete broken workflow, repeated frustration, or clear unmet demand.
- `is_monetizable=true` only when the pain plausibly maps to a software budget owner or operational buyer.
- `founder_pitch`, `news_analysis`, and generic `advice_thread` rows should mostly be hard negatives.
- mark B2C complaints as `is_pain=false` for this product, even if they are emotionally intense.
- if freshness is ambiguous, label `is_current_opportunity=false` until proven fresh.
