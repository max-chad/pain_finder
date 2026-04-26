# Eval harness slice plan

**Goal:** Add a reproducible evaluation harness for the Reddit pain parser so future parser changes can be judged against hand labels instead of vibe checks.

## Scope for this slice
- Add a checked-in seed dataset of labeled Reddit posts.
- Add a small evaluation library that can:
  - load seed posts + labels,
  - evaluate live classifier predictions or precomputed predictions,
  - compute pain / monetizable precision-recall metrics,
  - measure stale leakage,
  - report post-type confusion and label accuracies.
- Add a CLI entrypoint that writes metrics and predictions artifacts.
- Document how to run both offline and live Codex/DSPy evaluation.

## Planned files
- Create `eval_harness.py`
- Create `eval/README.md`
- Create `eval/seed_posts.jsonl`
- Create `eval/labels.jsonl`
- Create `eval/labels.schema.json`
- Create `eval/run_eval.py`
- Create `tests/test_eval_harness.py`
- Modify `README.md`

## TDD order
1. Write failing unit tests for metrics + confusion matrix + stale leakage.
2. Write failing test for live prediction materialization from `Classifier` output.
3. Write failing CLI/offline test that emits deterministic artifact files.
4. Implement minimal evaluation helpers.
5. Add checked-in seed posts + labels + docs.
6. Run focused tests, then full repo validation.

## Design choices
- Keep the harness outside the runtime pipeline/DB path; it should be cheap to run and not require writing to the production SQLite database.
- Support two modes:
  - `--predictions-path` for deterministic/offline evaluation,
  - `--live` for running the configured Codex/OpenAI/DSPy classifier stack on the seed set.
- Use an explicit `reference_now_ts` from labels or CLI so current-vs-evergreen evaluation stays deterministic over time.
- Reuse existing `Post`, `PainSignal`, and `Classifier` types to avoid parallel schemas.

## First metrics
- `pain`: precision / recall / f1
- `monetizable`: precision / recall / f1
- `stale_leakage_rate`
- `screening_false_negative_count`
- `post_type_confusion_matrix`
- `first_handness_accuracy`
- `buyer_authority_accuracy`

## Non-goals for this slice
- No DB migrations.
- No scheduler integration.
- No automatic cluster evaluation yet.
- No extra API calls in tests.
