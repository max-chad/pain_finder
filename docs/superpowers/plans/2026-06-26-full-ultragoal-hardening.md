# Full Ultragoal Hardening Plan - 2026-06-26

## Goal

Finish the broader `pain_finder` stabilization and improvement program beyond Phase 0. The result should be a defensible branch that has integrated or explicitly dispositioned the existing hardening and product/eval side-branch work, repaired any discovered regressions, and ends with a green local quality gate plus an explicit readiness verdict.

## Starting Point

- Current branch: `codex/full-ultragoal-hardening`, created from the green `codex/baseline-recovery` branch.
- Phase 0 baseline is complete and locally green.
- Hardening source branch: `codex/autonomous-audit-fixes`.
- Product/eval source branch: `bot/277606-external-review-plan`.

## Non-Negotiables

- Do not bulk-claim production readiness.
- Do not silently drop baseline fixes or reports.
- Do not add new paid production services or hidden network calls.
- Keep database evolution additive-only.
- Preserve budget pause semantics and fail-closed promotion behavior.
- Every accepted slice needs either focused tests, an existing regression test, or a recorded reason why coverage is indirect.
- Every rejected or deferred slice needs a reason.

## Story 1: Build Branch Intake Inventory

Create a dated intake report that inventories both side branches by invariant, not just by file count.

Required output:

- `docs/reports/2026-06-26-full-ultragoal-intake.md`
- Hardening branch groups: runtime safety, budget/accounting, provider parsing, source smoke/health, export/report safety, digest/operator resilience, Docker/CI, eval/test support.
- Product branch groups: evidence verifier, rejected-noise taxonomy, eval expansion, feedback loop, reports/research actions, buyer/competitor intelligence, digest/cluster improvements.
- For each group: `integrate now`, `rewrite smaller`, `defer`, or `reject`.

Acceptance:

- The report identifies concrete commits or files behind each group.
- The report lists likely merge conflicts and validation commands.

## Story 2: Integrate Runtime Hardening

Port or merge the high-confidence runtime hardening from `codex/autonomous-audit-fixes`.

Priority invariants:

- strict config validation;
- budget/resume correctness;
- usage event validation and accounting;
- bounded provider responses;
- source smoke/health checks;
- URL and export path safety;
- additive stale-migration repair;
- digest and operator callback resilience;
- Docker/CI safety guards.

Acceptance:

- Hardening functionality is present on the current branch.
- Baseline docs remain present.
- Focused hardening tests pass.
- Any unsafe or stale hardening item is dispositioned in the intake/report.

## Story 3: Integrate Evidence And Promotion Discipline

Port or rewrite the product/eval pieces that directly protect promotion quality.

Priority invariants:

- deterministic evidence verification;
- hard-negative rejected-noise taxonomy;
- fail-closed promotion eligibility;
- eval schema/labels updates for evidence and hard negatives;
- staged pain/evidence gates only if they remain coherent with current runtime code.

Acceptance:

- Promotion eligibility can fail closed against noisy/non-monetizable signals.
- Evidence claims are anchored to source text where surfaced.
- Eval or regression tests cover the accepted behavior.

## Story 4: Integrate Opportunity Intelligence Outputs

Port or rewrite product features that turn raw pain posts into analyst-useful opportunities.

Priority invariants:

- cluster-first digest/report improvements;
- static research report builder;
- feedback loop as future labels;
- research action workflow;
- buyer intelligence;
- competitor failure radar;
- research-friendly export fields.

Acceptance:

- Operator-facing outputs remain bounded and do not crash on malformed data.
- New modules are wired only where tests prove the contract.
- Deferred product surfaces are explicitly recorded rather than half-integrated.

## Story 5: Repository Coherence And Documentation

Align the repository story with the actual accepted behavior.

Required output:

- Update README/docs only to match implemented behavior.
- Add a final readiness report: `docs/reports/2026-06-26-full-ultragoal-readiness.md`.
- The readiness report must separate proven facts, source-branch work accepted, work deferred/rejected, remaining risks, and next operator steps.

Acceptance:

- Docs do not claim readiness beyond local evidence.
- The final report is concrete enough for a later PR/review.

## Story 6: Final Gate

Run the final quality gate on the finished branch.

Required checks:

```powershell
ruff check .
mypy db.py scraper.py openrouter.py classifier.py pipeline.py bot.py scheduler.py export_sheets.py main.py
pytest --cov=. --cov-fail-under=80 -q
```

Run safe optional checks if the integrated tooling exists and local environment permits:

```powershell
docker compose config -q
python healthcheck.py --fail-on-job-errors
python smoke_collect.py --source reddit --limit 1 --require-posts
```

Acceptance:

- Required checks pass, or any non-pass is repaired before completion.
- Optional checks are either passed or explicitly marked not run with the reason.
- `git status --short` is clean.
- Final `ai-slop-cleaner` pass is run on changed files.
- Independent final code review returns `APPROVE` and architecture review returns `CLEAR`.

## Done Definition

The ultragoal is complete only when:

- all six stories are complete or replaced by explicit steering;
- all accepted code is committed;
- final tests and review are clean;
- the branch contains an explicit readiness verdict;
- no hidden active work remains in `.omx/ultragoal`.
