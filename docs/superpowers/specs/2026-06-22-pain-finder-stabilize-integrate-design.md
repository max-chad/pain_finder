# Pain Finder Stabilize And Integrate Design

Date: 2026-06-22

## Context

`pain_finder` is a Telegram-controlled B2B pain discovery system with Reddit, Hacker News, review-source ingestion, LLM classification, deep dives, macro clustering, GTM generation, CSV/Sheets export, grouped digest delivery, and an evaluation harness.

The current repository state has a branch split:

- `main` is the active branch, but local validation is not fully green.
- `codex/autonomous-audit-fixes` contains a large production/security/runtime hardening line.
- `bot/277606-external-review-plan` contains a large product/evaluation/research workflow line.

The goal is not to add more isolated features immediately. The goal is to restore a trusted base, reconcile existing work, and turn the bot into an evidence-backed B2B opportunity radar.

## Selected Approach

Use a staged rescue approach.

1. Repair the current `main` baseline first.
2. Inventory and selectively integrate existing hardening work.
3. Inventory and selectively integrate existing product/evaluation work.
4. Consolidate the product around evidence-backed opportunity intelligence.
5. Finish with explicit readiness gates and a documented verdict.

This is preferred over a bulk merge because both side branches are large and touch overlapping runtime/product surfaces. Cherry-picking or rewriting smaller slices keeps validation meaningful and reduces hidden regression risk.

## Objectives

- Make `main` pass the project quality gates again.
- Preserve and reuse high-value work from existing branches instead of reinventing it.
- Make runtime controls trustworthy before expanding product intelligence.
- Shift the core product from "pain finder bot" to evidence-backed B2B opportunity radar.
- Produce a prioritized backlog that covers blockers, high-impact hardening, product bets, and smaller functional bugs.
- Keep every accepted change tied to a reason, regression or focused check, and residual-risk note.

## Non-Goals

- Do not bulk merge either side branch without review.
- Do not rewrite the whole application architecture.
- Do not turn Telegram into a full product UI; it remains the operator control surface.
- Do not claim production readiness from a small seed eval set.
- Do not add new paid external services or production dependencies without explicit approval.

## Architecture

The integration program is split into five layers.

### 1. Baseline Repair

Restore the active branch as a reliable working point.

Known current failures:

- `tests/test_eval_harness.py::test_run_eval_offline_writes_artifacts` hardcodes `/opt/repos/pain_finder/eval/run_eval.py`.
- Two scraper concurrency tests assert wall-clock duration and are flaky on Windows/Python 3.13.
- `mypy` did not complete within the initial local timeout and needs a refreshed check with a larger timeout or focused diagnosis.

Expected outcome:

- `ruff check .` passes.
- Focused fixed tests pass.
- Full pytest coverage gate passes.
- `mypy` status is known and documented.

### 2. Repository Reconciliation

Treat side branches as source material.

For each item from `codex/autonomous-audit-fixes` and `bot/277606-external-review-plan`, assign one status:

- `merge now`: high-confidence, scoped, tested, fits current direction.
- `rewrite smaller`: valuable but too broad or conflict-prone.
- `defer`: useful later but not needed for the next stable base.
- `reject`: no longer aligned, duplicative, or too risky.

The hardening branch is reviewed first because runtime correctness protects all later product work.

### 3. Runtime Control Plane

Strengthen the parts that protect money, data, and operator trust.

Priority surfaces:

- LLM budget semantics and `/resume` behavior.
- Usage accounting for all LLM-like spend paths, including DSPy and embeddings or explicit disabled-by-default handling.
- Provider compatibility and defensive response parsing.
- Additive SQLite migration repair under stale migration markers.
- Strict JSON and finite numeric persistence boundaries.
- Export/report/file-send path safety.
- Source smoke checks and local healthcheck.
- Docker/CI guardrails.
- Scheduler behavior under budget pause.

Runtime work comes before product expansion because better classification is not valuable on top of unstable budget, data, or deployment behavior.

### 4. Opportunity Intelligence Layer

Move product value from individual posts to evidence-backed opportunities.

Core concepts:

- Verified evidence: quoted evidence must be anchored to source text before promotion.
- Hard-negative discipline: founder pitches, news, generic advice, B2C noise, stale items, solved issues, and shill-heavy rows should fail closed.
- Opportunity thesis: buyer, workflow, workaround, incumbent failure, urgency, source freshness, evidence, confidence, and next research action.
- Cluster-first digest: recurring pain clusters should become the primary decision unit, with posts as evidence.
- Feedback loop: favorites, discards, deep dives, GTM actions, and report feedback should inform eval and calibration.
- GTM output should become validation/research guidance, not only naming and copy generation.

### 5. Operator Experience

Telegram remains a compact control surface.

Operator-facing behavior should be bounded and graceful:

- Callback payloads must stay within Telegram limits.
- `/digest`, `/gtm`, `/export`, `/macro`, callbacks, scheduler jobs, and healthcheck should return clear partial output or actionable errors.
- Malformed rows, stale buttons, old SQLite schemas, and malformed provider payloads should not crash operator flows.
- Reports, digest documents, CSV/Sheets exports, and local research artifacts should carry the main decision value.

## Behavior Rules

### Main Branch

`main` is the only final truth branch. Side branches are reviewed inputs, not automatic replacements.

### Integration

Do not cherry-pick large ranges blindly. Integrate by invariant and verify each batch.

Recommended hardening intake order:

1. Test reliability on Windows.
2. Migration repair.
3. Budget and resume semantics.
4. LLM/provider accounting and defensive parsing.
5. Source health/smoke checks.
6. Export/report path safety.
7. Strict JSON and non-finite numeric guards.
8. Scheduler and digest resilience.
9. Telegram callback and command UX bounds.

Recommended product intake order:

1. Evidence verifier.
2. Rejected-noise taxonomy and hard negatives.
3. Expanded eval schema and dataset.
4. Feedback loop.
5. Report builder and research actions.
6. Competitor radar and buyer intelligence.
7. Cluster-first digest/report refinements.

### Promotion Gates

`promotion_eligible` must fail closed.

Promotion requires:

- verified evidence;
- first-hand or credible buyer-authority signal;
- sufficient freshness or explicit evergreen rationale;
- acceptable source confidence;
- no hard-negative type;
- no unresolved shill/noise flag.

High WTP, pain language, or generated summary quality is not enough.

### Budget

Budget is a hard control, not advisory metadata.

Every spend-producing path must either:

- be recorded in `llm_usage_events`; or
- be disabled by default; or
- be explicitly documented as unmetered with a separate hard cap.

Missing model pricing must not silently create unlimited zero-cost calls.

### Evaluation

Classifier, prompt, evidence, scoring, and promotion changes require an eval or regression hook.

Minimum eval dimensions:

- hard-negative false-positive rate;
- stale leakage;
- monetizable precision;
- verified evidence match;
- top-N useful insight rate;
- cluster duplicate rate when clustering changes.

The checked-in eval set may remain a starter benchmark, but readiness claims require larger measured artifacts or an explicit waiver.

### Traceability

Each accepted fix or feature should record:

- reason;
- changed files;
- validation;
- residual risk.

This can live in `AGENT_NOTES.md`, a dated report, or another agreed project note.

## Rollout Plan

### Phase 0: Baseline Recovery

Tasks:

- Fix the hardcoded eval runner path.
- Replace wall-clock scraper concurrency assertions with deterministic overlap assertions.
- Set explicit pytest asyncio fixture loop scope if needed.
- Re-run focused tests and full pytest coverage gate.
- Re-run `mypy` with enough time or diagnose why it does not complete.

Acceptance:

- Full pytest gate passes.
- Lint passes.
- Type-check status is known.

### Phase 1: Hardening Intake

Tasks:

- Inventory `codex/autonomous-audit-fixes`.
- Group commits by invariant.
- Integrate high-confidence slices.
- Prefer existing regression tests from the branch when they still fit.
- Rewrite overly broad changes into smaller patches when needed.

Acceptance:

- Each integrated hardening slice has a focused test or documented coverage.
- No unrelated branch churn is introduced.
- Full gate passes after meaningful batches.

### Phase 2: Product And Eval Intake

Tasks:

- Inventory `bot/277606-external-review-plan`.
- Prioritize evidence, hard negatives, eval expansion, and feedback before larger product surfaces.
- Keep product additions behind measurable behavior.
- Avoid broad product claims until eval artifacts support them.

Acceptance:

- Promotion fail-closed behavior is covered by tests.
- Eval harness can measure the new taxonomy dimensions.
- Product surfaces render evidence-backed opportunities rather than raw model enthusiasm.

### Phase 3: Consolidated Opportunity Radar

Tasks:

- Update README and docs around evidence-backed B2B opportunity radar.
- Align digest, export, report, and GTM around opportunity thesis and research actions.
- Add readiness report with proven and unproven claims.

Acceptance:

- Operator outputs are coherent and decision-oriented.
- Docs match actual runtime behavior.
- Readiness verdict is explicit.

### Phase 4: Final Gate

Run the standard project gates:

```powershell
ruff check .
mypy db.py scraper.py openrouter.py classifier.py pipeline.py bot.py scheduler.py export_sheets.py main.py
pytest --cov=. --cov-fail-under=80 -q
```

If Docker, healthcheck, or smoke tooling is integrated, also run the safe relevant checks:

```powershell
docker compose config -q
python healthcheck.py
python smoke_collect.py --source reddit --limit 1
```

The smoke command should only run where environment and network assumptions are valid.

## Initial Backlog

### Blockers

- Restore green test baseline on `main`.
- Resolve `mypy` timeout or document a known type-check status.
- Fix budget/resume semantics so temporary resume remains temporary.
- Prevent zero-cost unlimited budget behavior when model pricing is missing.
- Decide how DSPy and embeddings are budget-accounted or disabled.

### High Priority

- Repair stale migration marker behavior.
- Preserve daily digest scheduling under LLM budget pause where digest does not spend LLM budget.
- Add defensive provider payload parsing.
- Bound Telegram callback data for long post IDs.
- Make `/gtm` command handle expected generator failures.
- Harden digest rendering against malformed DB rows.
- Restore or port healthcheck and source smoke tooling if accepted.

### Product Priority

- Implement evidence-first promotion.
- Add hard-negative eval rows and metrics.
- Expand eval set toward 100-150 labeled examples.
- Use feedback actions as labels.
- Make clusters the primary digest/report unit.
- Extend GTM context with evidence, buyer authority, comments, source age, and score components.
- Add validation playbook and research actions to GTM output.

### Polish

- Add source/query ROI reporting.
- Improve CSV/Sheets handoff fields.
- Add competitor displacement narratives.
- Add clearer readiness/reporting docs for analyst-controlled runs.

## Risks

- Side branches are large and may conflict. Mitigation: integrate by invariant, not by branch wholesale.
- Some branch work may be stale relative to `main`. Mitigation: rerun targeted tests after each port.
- Product features can outpace eval evidence. Mitigation: require eval or regression hooks before promotion surface changes.
- Budget fixes may expose previously hidden spend or require config decisions. Mitigation: fail clearly and document required env.
- Health/smoke commands may need environment-specific handling. Mitigation: keep them local/read-only and document when to run them.

## Open Questions

- Whether `codex/autonomous-audit-fixes` should become a long-lived rescue branch or only a patch source.
- Whether DSPy should remain enabled by default after budget/accounting review.
- Which ICP should become the first explicit wedge for opportunity ranking.
- Whether local static reports should become the primary analyst surface or remain secondary to Telegram/docx.

These questions do not block Phase 0. They should be answered before product/eval integration becomes broad.
