# Pain Finder Staged Clarity Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Align the repo's docs, readiness gates, runtime control plane, and evals with the evidence-backed B2B opportunity intelligence framing, while keeping `main` green.

**Architecture:** Treat clarity and hardening as one pass. First fix the product story and operator vocabulary, then make readiness and fail-closed behavior explicit, then expand evals around clusters and opportunity candidates. Keep the low-risk runtime guards separate from the structural budget rework so each phase stays testable on its own.

**Tech Stack:** Python 3.13, SQLite, Telegram bot handlers, OpenAI-compatible LLM clients, pytest, ruff, mypy, GitHub Actions, Markdown docs.

---

## File Map

- `README.md`: top-level product framing, env bootstrap, readiness commands, and operator surface.
- `eval/README.md`: product-level eval framing, labels, and benchmark caveats.
- `healthcheck.py`: readiness gate and runtime integrity checks.
- `smoke_collect.py`: read-only source smoke checks and review-target validation.
- `main.py`: startup ordering and review-target preflight.
- `pipeline.py`: keep valid runs alive when one dedup/embed path fails.
- `deduplicator.py`: best-effort backfill and merge behavior.
- `budget.py`, `openrouter.py`, `db.py`: spend admission, usage accounting, routing, and runtime-row integrity.
- `tests/test_config.py`, `tests/test_healthcheck.py`, `tests/test_smoke_collect.py`, `tests/test_main.py`, `tests/test_pipeline.py`, `tests/test_deduplicator.py`, `tests/test_budget.py`, `tests/test_openrouter.py`, `tests/test_dspy_parser.py`, `tests/test_eval_harness.py`, `tests/test_db.py`: regression coverage for the contracts above.
- `.github/workflows/test.yml`: CI quality and readiness gates.
- `docs/reports/2026-06-26-full-ultragoal-readiness.md`: final closeout and residual-risk writeup.

### Task 1: Product And Docs Clarity

**Files:**
- Modify `README.md`
- Modify `eval/README.md`
- Modify `tests/test_config.py`

- [x] **Step 1: Reframe the README opener**

  Replace the parser-centric opener with the operator-control framing: `pain_finder is an operator-controlled, evidence-backed B2B opportunity intelligence pipeline.` Add a short glossary block that defines `evidence`, `hard negative`, `cluster`, `opportunity candidate`, `promotion eligible`, and `decision surface`.

- [x] **Step 2: Reword the eval README**

  Make `eval/README.md` describe the harness as a starter scorecard for product-level opportunity quality, not just a parser benchmark. Keep the 100-150 labeled examples target, but state clearly that this is a target direction, not a readiness claim.

- [x] **Step 3: Keep the README pinning tests honest**

  Update `tests/test_config.py::test_readme_smoke_collect_all_documents_review_target_requirement` so the assertions still pin the smoke-check docs after the wording change.

**Validation:**
- `pytest tests/test_config.py -q`

**Success criteria:**
- The docs consistently say Telegram is the control plane and clusters/opportunity candidates are the decision unit.
- The README still documents the required smoke command and review-target requirement.
- The eval README no longer reads like a parser-only artifact.

### Task 2: Readiness And DevEx Fixes

**Files:**
- Modify `README.md`
- Modify `healthcheck.py`
- Modify `smoke_collect.py`
- Modify `.github/workflows/test.yml`
- Modify `tests/test_healthcheck.py`
- Modify `tests/test_smoke_collect.py`
- Modify `tests/test_config.py`

- [x] **Step 1: Fix the bootstrap story in the README**

  Add an explicit bootstrap block that shows the required env values before `python main.py`, and state plainly that missing env fails fast at `config.py` import time.

- [x] **Step 2: Remove stale readiness wording**

  Replace every `healthcheck.py --strict` reference in repo docs or comments with `python healthcheck.py --fail-on-job-errors`. Keep Docker liveness separate from readiness gating.

- [x] **Step 3: Put readiness commands into CI**

  Extend `.github/workflows/test.yml` so the quality gate also exercises `python healthcheck.py --fail-on-job-errors` and a read-only smoke command such as `python smoke_collect.py --source reddit --subreddit python --limit 1 --require-posts` after the unit-test stage, with whatever env bootstrap is needed to make the step deterministic.

- [x] **Step 4: Keep the help text and tests aligned**

  Update the healthcheck and smoke tests so the command-line help and documented operator commands match the real CLI.

**Validation:**
- `pytest tests/test_healthcheck.py tests/test_smoke_collect.py tests/test_config.py -q`

**Success criteria:**
- README quickstart no longer hides the required env bootstrap.
- The repo only references the real readiness flag, `--fail-on-job-errors`.
- CI has an explicit readiness surface instead of relying on lint and unit tests alone.

### Task 3: Fail-Open Runtime Hardening

**Files:**
- Modify `main.py`
- Modify `pipeline.py`
- Modify `deduplicator.py`
- Modify `tests/test_main.py`
- Modify `tests/test_pipeline.py`
- Modify `tests/test_deduplicator.py`

- [x] **Step 1: Move review-target validation earlier**

  Make review-target parsing and validation happen before database initialization and dedup backfill. Invalid `REVIEW_TARGETS_JSON` should fail early, not after expensive startup work.

- [x] **Step 2: Keep one bad embed from killing a good run**

  Make `pipeline.py` and `deduplicator.py` continue when a single embed or merge fails. The valid rows should still be processed, stored, and counted.

- [x] **Step 3: Preserve partial progress explicitly**

  Record partial-failure outcomes in logs or counters so a run that loses one embed is clearly marked as degraded, not silently successful.

**Validation:**
- `pytest tests/test_main.py tests/test_pipeline.py tests/test_deduplicator.py -q`

**Success criteria:**
- Bad review config fails before DB/dedup bootstrap.
- A single embedding failure does not abort the entire analysis run.
- Dedup backfill stays best-effort instead of acting like a hard stop.

### Task 4: Budget And Accounting Hardening

**Files:**
- Modify `budget.py`
- Modify `openrouter.py`
- Modify `db.py`
- Modify `healthcheck.py`
- Modify `tests/test_budget.py`
- Modify `tests/test_openrouter.py`
- Modify `tests/test_db.py`

- [x] **Step 1: Stop swallowing accounting failures**

  Make usage-write failures visible to the caller instead of logging and pretending the spend path succeeded. A failed `llm_usage_events` write should be an explicit runtime problem, not a quiet warning.

- [x] **Step 2: Fail closed on malformed Codex routing claims**

  In `openrouter.py`, treat missing or malformed `ChatGPT-Account-ID` claim data as a routing failure that is surfaced to the caller, not as a silent fallback to generic chat routing.

- [x] **Step 3: Add integrity checks to healthcheck**

  Expand `healthcheck.py` so readiness includes `llm_usage_events` and runtime-row integrity, not just basic storage writability.

- [x] **Step 4: Keep DB validation strict**

  Make sure `db.py` continues to reject non-finite or otherwise invalid usage data so accounting failures are caught at the right boundary.

**Validation:**
- `pytest tests/test_budget.py tests/test_openrouter.py tests/test_db.py tests/test_healthcheck.py -q`

**Success criteria:**
- Accounting failures are explicit and reviewable.
- Codex routing does not silently degrade when account claim data is bad.
- Healthcheck can tell the difference between a writable DB and a trustworthy runtime state.

### Task 5: Product-Level Eval Expansion

**Files:**
- Modify `eval/labels.schema.json`
- Modify `eval/labels.jsonl`
- Modify `eval/run_eval.py`
- Modify `eval/README.md`
- Modify `tests/test_eval_harness.py`
- Modify `tests/test_config.py`

- [x] **Step 1: Extend the eval schema toward decision quality**

  Add metrics and labels for hard negatives, evidence grounding, current-opportunity freshness, and cluster usefulness. Keep parser accuracy metrics, but do not let them remain the only signal.

- [x] **Step 2: Grow the starter label set**

  Add or relabel examples so the checked-in set contains enough founder pitches, generic advice, B2C noise, stale items, and solved items to exercise the hard-negative path.

- [x] **Step 3: Reword the eval README**

  State clearly that the checked-in set is a starter benchmark and that product readiness needs larger measured artifacts or an explicit waiver.

- [x] **Step 4: Keep the harness contract testable**

  Update `tests/test_eval_harness.py` so the runtime classifier wiring and output schema still match the new eval dimensions.

**Validation:**
- `pytest tests/test_eval_harness.py tests/test_config.py -q`

**Success criteria:**
- The eval harness measures product-level quality, not just parser output.
- The starter set explains what it can prove and what it cannot prove.
- The docs and tests agree on the eval target direction.

### Task 6: Structural Budget Rework Later

**Files:**
- Modify `budget.py`
- Modify `classifier.py`
- Modify `openrouter.py`
- Modify `tests/test_budget.py`
- Modify `tests/test_classifier.py`
- Modify `tests/test_openrouter.py`

- [x] **Step 1: Introduce spend reservation or serialization**

  Add a serialized admission path so concurrent LLM calls cannot all pass a stale preflight and overshoot the daily cap.

- [x] **Step 2: Reconcile post-call accounting with admission**

  Keep the definitive spend decision close to the actual request, then reconcile after the call so future work can pause correctly even under concurrency.

- [x] **Step 3: Verify the concurrency contract**

  Add a regression test that makes parallel classifications compete for the same budget and proves the cap is enforced without silent overshoot.

**Validation:**
- `pytest tests/test_budget.py tests/test_classifier.py tests/test_openrouter.py -q`

**Success criteria:**
- Budget admission is monotonic under concurrency, not just best-effort preflight.
- Post-call accounting cannot silently overrun the day cap.
- The later structural fix stays separate from the quick accounting hardening above.

### Task 7: Closeout And Readiness Report

**Files:**
- Modify `docs/reports/2026-06-26-full-ultragoal-readiness.md`

- [x] **Step 1: Write the final verdict**

  Summarize what was accepted, what was deferred, what changed in the docs, and which runtime risks remain.

- [x] **Step 2: Record the exact validation results**

  Capture the commands that passed, any commands that were intentionally skipped, and the reason for each skip.

**Validation:**
- `ruff check .`
- `mypy db.py scraper.py openrouter.py classifier.py pipeline.py bot.py scheduler.py export_sheets.py digest_delivery.py main.py healthcheck.py smoke_collect.py url_safety.py dspy_parser.py eval/run_eval.py eval_harness.py`
- `pytest --cov=. --cov-fail-under=80 -q`

**Success criteria:**
- The readiness report separates proven facts from deferred work.
- The repo story, docs, and runtime gates all describe the same system.
- The final write-up is concrete enough for a later PR or review.
