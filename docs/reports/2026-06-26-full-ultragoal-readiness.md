# Full Ultragoal Readiness Report - 2026-06-26

## Scope

Branch: `codex/full-ultragoal-hardening`

This is a local closeout report. It records what actually landed and the final green gate; it is not a production deployment certification.

## Proven Facts

- The branch started from `codex/baseline-recovery` and kept the June baseline docs intact.
- Docs clarity landed:
  - `README.md` now frames `pain_finder` as an operator-controlled, evidence-backed B2B opportunity intelligence pipeline.
  - `eval/README.md` now frames `eval/` as a starter product-quality benchmark, not readiness proof.
- Readiness/devex landed:
  - `healthcheck.py` now separates Docker liveness from operator readiness via `--fail-on-job-errors`.
  - `smoke_collect.py` is read-only and can fail closed when a requested source returns zero posts.
- Fail-open runtime hardening landed:
  - OpenRouter now caps response size, normalizes usage payloads, and raises `OpenRouterUsageAccountingError` if usage persistence fails.
- Budget/accounting hardening landed:
  - `BudgetGuard` preserves pause/resume semantics, records spend, and pauses when the cap is crossed.
- Structural concurrency fixes landed:
  - OpenRouter and DSPy paths both now use the guarded in-process admission flow, so spend checks and usage writes do not race.
- First eval-expansion bundle landed:
  - `eval/run_eval.py`, `eval/labels.jsonl`, `eval/labels.schema.json`, and the eval harness tests now carry a starter `cluster_useful` contract.
- The accepted product/eval rewrite stayed smaller than the broader source branch and focused on the tested evidence/promotion/eval core rather than wholesale branch import.

## Deferred / Intentionally Thin

- The checked-in eval seed remains small: 10 labeled rows, with only 2 `cluster_useful` labels. It is a starter benchmark, not a release gate.
- Broader report/research-action surfaces were left deferred on purpose.
- The new budget admission lock is process-local; multi-process spend coordination is still out of scope.
- Some module-level coverage percentages remain below 80, even though the repo-wide coverage gate passed.
- Local tests do not prove Telegram delivery, external source availability, or operator acceptance in the target environment.

## Final Gate

- `ruff check .` -> pass
- `mypy db.py scraper.py openrouter.py classifier.py pipeline.py bot.py scheduler.py export_sheets.py digest_delivery.py main.py healthcheck.py smoke_collect.py url_safety.py dspy_parser.py eval/run_eval.py eval_harness.py` -> pass
- `pytest --cov=. --cov-fail-under=80 -q` -> `462 passed`, coverage `91.79%`

## Verdict

Locally, the branch is green and the implemented slices are coherent enough for review/PR closeout. It is still not a production certification.
