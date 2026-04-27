# Evaluation harness

This directory is the reproducible scorecard for the Reddit pain parser and opportunity-ranking pipeline.

## What is in here

- `seed_posts.jsonl` — checked-in starter dataset of Reddit-like posts.
- `labels.jsonl` — hand labels for the seed set.
- `labels.schema.json` — label shape and allowed taxonomy values.
- `label_guide.md` — labeling rules, positive/negative examples, and hard-negative taxonomy.
- `baselines.example.yaml` — documented baseline-comparison naming convention.
- `run_eval.py` — CLI for evaluating either:
  - live classifier output from the configured runtime,
  - a saved predictions file, or
  - multiple named offline baseline prediction files in one command.

## Why this exists

The parser has grown beyond simple keyword search:

- source-age buckets,
- typed post taxonomy,
- cheap screening,
- composite scoring,
- verified evidence quality,
- evidence-first promotion rules,
- comment signals,
- canonical clusters.

Without a labeled eval set, every parser change turns into vibe-based debate. This harness makes prompt/schema/scoring changes measurable.

## Seed-set caveat

The checked-in seed set is still a starter benchmark, not a final quality gate. It now includes:

- 60 total labeled examples,
- 54 hard negatives,
- B2B workflow positives with expected cluster keys,
- consumer/B2C, founder-pitch, news, solved-issue, generic recommendation, vendor-comparison, and low-context negative examples.

Target direction:

- grow toward 100-150 labeled posts,
- keep subreddit/domain diversity,
- keep expanding hard negatives before widening recall,
- refresh labels when taxonomy changes.

## Label fields

Every `labels.jsonl` row must include:

- `is_pain`
- `is_monetizable`
- `post_type`
- `pain_type`
- `expression_type`
- `first_handness`
- `buyer_authority`
- `intensity_label`
- `urgency_label`
- `wtp_label`
- `current_workaround`
- `incumbent_failure`
- `evidence_quality`
- `evidence_expected` (derived compatibility boolean)
- `opportunity_type`
- `is_current_opportunity`
- `hard_negative_type`
- `reference_now_ts`

Optional but supported:

- `expected_cluster_key`
- `evidence_relevance`
- `source_link_validity`
- `feedback_useful`
- `notes`

`reference_now_ts` is important: it freezes the freshness boundary so `current_opportunity` vs `evergreen_pain` stays deterministic over time.

Current checked-in seed labels use:

- `reference_now_ts = 1776729600`
- which corresponds to `2026-04-21T00:00:00Z`

See `label_guide.md` before adding labels.

## Metrics reported

Core classifier metrics:

- `pain`: precision / recall / f1
- `monetizable`: precision / recall / f1
- `stale_leakage.rate`
- `screening_false_negative_count`
- `post_type_confusion`
- `first_handness_accuracy`
- `buyer_authority_accuracy`

Evidence metrics:

- `evidence.coverage_rate`
- `evidence.exact_match_rate`
- `evidence.needs_human_review_rate`
- `evidence.quality_counts`
- `evidence.manual_relevance`
- `evidence.source_link_validity`

Hard-negative metrics:

- `hard_negatives.false_positive_rate`
- `hard_negatives.by_type.*.false_positive_rate`

Cluster/usefulness metrics:

- `clusters.duplicate_rate`
- `clusters.purity`
- `top_n_useful_rate.top_1/top_3/top_5/top_10`
- `cost_per_useful_insight`
- `latency_ms_per_prediction`

Metrics that cannot be computed because labels/artifact fields are absent return `null`, not guessed defaults.

## Run against live Codex / DSPy stack

This uses the same runtime defaults as the app. If your env already points at Codex + DSPy, the harness will use that.

```bash
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

## Compare named baselines offline

Use repeated `--baseline-predictions NAME=PATH` arguments. Each baseline gets its own `metrics.json` and `predictions.jsonl` under the output directory, plus a top-level `baseline_summary.json`. The first named baseline is treated as the reference baseline; later baselines get `*_delta` comparisons against it.

```bash
python eval/run_eval.py \
  --dataset eval/seed_posts.jsonl \
  --labels eval/labels.jsonl \
  --baseline-predictions current=eval/artifacts/current/predictions.jsonl \
  --baseline-predictions rules_only=eval/artifacts/rules-only/predictions.jsonl \
  --baseline-predictions no_prescreen=eval/artifacts/no-prescreen/predictions.jsonl \
  --output-dir reports/eval/seed-offline-comparison \
  --reference-now-ts 1776729600
```

See `baselines.example.yaml` for the preferred baseline names: `current`, `rules_only`, `no_prescreen`, `llm_only`, and `dspy`.

## Score calibration artifact

Wave 5 adds a deterministic, review-only calibration helper for visible opportunity score components. It evaluates deterministic default weights against saved labels/predictions and writes review-only recommendations, but deliberately sets `auto_apply=false`; never wire its output directly into runtime without a regression pass.

```bash
python eval/calibrate_score.py \
  --labels eval/labels.jsonl \
  --predictions eval/artifacts/seed-live/predictions.jsonl \
  --output eval/artifacts/score-calibration.json \
  --top-n 10
```

## Artifact layout

Single-mode runs write:

- `metrics.json`
- `predictions.jsonl`
- `mvp_thresholds.json`
- `run_manifest.json`

inside the `--output-dir` you pass.

Baseline-comparison runs write:

- `<baseline>/metrics.json`
- `<baseline>/predictions.jsonl`
- `<baseline>/mvp_thresholds.json`
- `baseline_summary.json`
- `run_manifest.json`

## Wave 9.2 MVP threshold assessment

Every `run_eval.py` execution now writes a conservative `mvp_thresholds.json` assessment next to the metrics artifact. It measures the Wave 9.2 release gates, but fail-closes: a run is **not usable for MVP** unless all metric targets pass and the eval set is an expanded benchmark of at least 100 labeled rows, or an explicit waiver is supplied with `--waive-mvp-benchmark-size`.

Each run also writes `run_manifest.json`, a traceability packet that links dataset/label inputs, prediction/metrics/threshold artifacts, baseline artifacts where applicable, dataset size, `reference_now_ts`, and the MVP threshold summary. Both `mvp_thresholds.json` and `run_manifest.json` carry `readiness_scope=eval_audit_gate_only` and `production_ready_claimed=false`; they are eval/audit gate artifacts, not production-readiness certification.

Targets checked in the artifact:

| MVP metric | Target |
| --- | ---: |
| Pain precision | >= 0.75 |
| Pain recall | >= 0.60 |
| Evidence exact match | >= 0.95 |
| Monetizable precision | >= 0.65 |
| Top-10 useful insight rate | >= 0.50 |
| Cluster duplicate rate | <= 0.20 |

The threshold file includes `usable_for_mvp`, `release_decision`, per-metric `checks`, and a `benchmark_gate` showing dataset size, minimum size, and whether the expanded benchmark gate was explicitly waived. Missing metrics such as absent `top_n_useful_rate.top_10` are marked `not_evaluated`, not treated as passing.

## Labeling guidance

Prefer these rules when expanding the set:

- `is_pain=true` only when there is a concrete broken workflow, repeated frustration, or clear unmet demand.
- `is_monetizable=true` only when the pain plausibly maps to a software budget owner or operational buyer.
- `founder_pitch`, `news_analysis`, and generic `advice_thread` rows should mostly be hard negatives.
- mark B2C complaints as `is_pain=false` for this product, even if they are emotionally intense.
- if freshness is ambiguous, label `is_current_opportunity=false` until proven fresh.
- hard negatives should be expanded first whenever a recall change creates new false positives.
