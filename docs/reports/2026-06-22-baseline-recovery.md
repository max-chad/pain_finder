# Baseline Recovery Report - 2026-06-22

## Scope

This report records the Phase 0 baseline recovery for `main` work carried out on branch `codex/baseline-recovery`.

## Changes

- Made the offline eval CLI test resolve `eval/run_eval.py` from the local checkout.
- Replaced scraper concurrency wall-clock assertions with deterministic in-flight request counting.
- Pinned `pytest-asyncio` fixture loop scope to `function`.

## Validation

| Gate | Command | Result |
| --- | --- | --- |
| Lint | `ruff check .` | PASS: `All checks passed!` |
| Focused repaired tests | `pytest tests/test_eval_harness.py::test_run_eval_offline_writes_artifacts tests/test_scraper.py::test_fetch_public_json_requests_feeds_concurrently tests/test_scraper.py::test_fetch_oauth_json_requests_feeds_concurrently -q` | PASS: `3 passed in 2.05s` |
| Full pytest coverage | `pytest --cov=. --cov-fail-under=80 -q` | PASS: `231 passed in 66.35s`; total coverage `89.43%`; coverage threshold `80%` reached. |
| Mypy | `mypy db.py scraper.py openrouter.py classifier.py pipeline.py bot.py scheduler.py export_sheets.py main.py` | PASS: `Success: no issues found in 9 source files`; note emitted for unchecked untyped function bodies in `bot.py:497`. |

## Residual Risk

- This phase does not integrate hardening or product/eval changes from side branches.
- The full test suite can still reveal environment-specific failures on other machines; CI must remain the final shared check.
- Mypy is green under the current relaxed project settings in `pyproject.toml`; it does not imply strict typed coverage.

## Next Step

Proceed to a hardening intake inventory for `codex/autonomous-audit-fixes` after reviewing this baseline report.
