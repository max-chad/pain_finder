# Baseline Recovery Report - 2026-06-22

## Scope

This report records the Phase 0 baseline recovery for `main` work carried out on branch `codex/baseline-recovery`.

## Changes

- Made the offline eval CLI test resolve `eval/run_eval.py` from the local checkout.
- Replaced scraper concurrency wall-clock assertions with deterministic in-flight request counting.
- Pinned `pytest-asyncio` fixture loop scope to `function`.
- Raised the `pytest-asyncio` dependency floor to a version that supports `asyncio_default_fixture_loop_scope`.

## Validation

| Gate | Command | Result |
| --- | --- | --- |
| Lint | `ruff check .` | PASS: `All checks passed!` |
| Focused repaired tests | `pytest tests/test_eval_harness.py::test_run_eval_offline_writes_artifacts tests/test_scraper.py::test_fetch_public_json_requests_feeds_concurrently tests/test_scraper.py::test_fetch_oauth_json_requests_feeds_concurrently -q` | PASS: `3 passed in 2.15s` |
| Full pytest coverage | `pytest --cov=. --cov-fail-under=80 -q` | PASS: `231 passed in 40.82s`; total coverage `89.43%`; coverage threshold `80%` reached. |
| Mypy | `mypy db.py scraper.py openrouter.py classifier.py pipeline.py bot.py scheduler.py export_sheets.py main.py` | PASS: `Success: no issues found in 9 source files`; note emitted for unchecked untyped function bodies in `bot.py:497`. |

## Review Cleanup

- Independent code review identified a LOW dependency-floor mismatch: `pytest.ini` uses `asyncio_default_fixture_loop_scope`, while `requirements.txt` allowed `pytest-asyncio>=0.23`.
- Raised the floor to `pytest-asyncio>=0.24`, matching the configuration option introduced in the v0.24 migration path.
- `python -m pip check` is not clean in the shared global Python environment because unrelated installed packages `mysorka` and `spotdl` pin conflicting versions of `aiogram`, `alembic`, `fastapi`, `redis`, `sqlalchemy`, and `uvicorn`; no `pain_finder` dependency conflict was reported.

## Residual Risk

- This phase does not integrate hardening or product/eval changes from side branches.
- The full test suite can still reveal environment-specific failures on other machines; CI must remain the final shared check.
- Mypy is green under the current relaxed project settings in `pyproject.toml`; it does not imply strict typed coverage.
- `pytest.ini` now makes function-scoped async fixtures the default; future broader async fixtures should declare their intended `loop_scope` explicitly.
- The scraper concurrency tests intentionally assert current all-feeds fan-out. Revisit that contract before adding rate limiting or quota-aware scraping.

## Next Step

Proceed to a hardening intake inventory for `codex/autonomous-audit-fixes` after reviewing this baseline report.
