# Baseline Recovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restore the current `main` branch to a trusted, locally green baseline before integrating hardening or product/eval work from side branches.

**Architecture:** This plan changes only the validation surface and traceability docs. It fixes the known failing tests with portable, deterministic assertions, records the baseline outcome, and leaves runtime/product behavior unchanged.

**Tech Stack:** Python 3.13 on Windows, pytest, pytest-asyncio, pytest-cov, ruff, mypy, PowerShell, Git.

---

## File Structure

- Modify: `tests/test_eval_harness.py`
  - Responsibility: offline eval CLI test should locate `eval/run_eval.py` relative to the repository checkout, not a fixed Linux path.
- Modify: `tests/test_scraper.py`
  - Responsibility: scraper feed-concurrency tests should prove request overlap deterministically, not depend on machine wall-clock timing.
- Modify: `pytest.ini`
  - Responsibility: pin pytest-asyncio fixture loop scope to avoid version-dependent async fixture behavior.
- Create: `docs/reports/2026-06-22-baseline-recovery.md`
  - Responsibility: record commands, results, and remaining validation status after baseline repair.

## Task 1: Make Eval CLI Test Path Portable

**Files:**
- Modify: `tests/test_eval_harness.py:304`
- Test: `tests/test_eval_harness.py`

- [ ] **Step 1: Confirm the current focused failure**

Run:

```powershell
pytest tests/test_eval_harness.py::test_run_eval_offline_writes_artifacts -q
```

Expected before the fix:

```text
FAILED tests/test_eval_harness.py::test_run_eval_offline_writes_artifacts
FileNotFoundError: ... C:\opt\repos\pain_finder\eval\run_eval.py
```

- [ ] **Step 2: Replace the hardcoded path with a repo-relative path**

In `tests/test_eval_harness.py`, replace:

```python
    runpy.run_path("/opt/repos/pain_finder/eval/run_eval.py", run_name="__main__")
```

with:

```python
    run_eval_path = Path(__file__).resolve().parents[1] / "eval" / "run_eval.py"
    runpy.run_path(str(run_eval_path), run_name="__main__")
```

`Path` is already imported at the top of this file.

- [ ] **Step 3: Run the focused eval test**

Run:

```powershell
pytest tests/test_eval_harness.py::test_run_eval_offline_writes_artifacts -q
```

Expected after the fix:

```text
1 passed
```

- [ ] **Step 4: Commit the eval path fix**

Run:

```powershell
git add -- tests/test_eval_harness.py
git commit -m "test: make eval runner path portable"
```

Expected:

```text
[main <hash>] test: make eval runner path portable
```

## Task 2: Make Scraper Concurrency Tests Deterministic

**Files:**
- Modify: `tests/test_scraper.py:1-2`
- Modify: `tests/test_scraper.py:497-518`
- Modify: `tests/test_scraper.py:600-621`
- Test: `tests/test_scraper.py`

- [ ] **Step 1: Confirm the current focused failures**

Run:

```powershell
pytest tests/test_scraper.py::test_fetch_public_json_requests_feeds_concurrently tests/test_scraper.py::test_fetch_oauth_json_requests_feeds_concurrently -q
```

Expected before the fix on this workstation:

```text
FAILED tests/test_scraper.py::test_fetch_public_json_requests_feeds_concurrently
FAILED tests/test_scraper.py::test_fetch_oauth_json_requests_feeds_concurrently
assert <elapsed> < 0.12
```

- [ ] **Step 2: Remove the unused wall-clock import**

In `tests/test_scraper.py`, replace:

```python
import asyncio
import time
```

with:

```python
import asyncio
```

- [ ] **Step 3: Replace the public JSON elapsed-time assertion**

In `test_fetch_public_json_requests_feeds_concurrently`, replace the body after the `scraper = RedditScraper(...)` block with:

```python
    active_requests = 0
    max_active_requests = 0

    async def delayed_payload(*, client, url, params, headers):
        nonlocal active_requests, max_active_requests
        active_requests += 1
        max_active_requests = max(max_active_requests, active_requests)
        await asyncio.sleep(0.05)
        active_requests -= 1
        return {"data": {"children": []}}

    with patch.object(scraper, "_request_json_with_retries", side_effect=delayed_payload):
        posts = await scraper._fetch_public_json("python", limit=30)

    assert posts == []
    assert max_active_requests == 3
```

This keeps the concurrency contract covered without depending on `httpx.AsyncClient` startup time.

- [ ] **Step 4: Replace the OAuth JSON elapsed-time assertion**

In `test_fetch_oauth_json_requests_feeds_concurrently`, replace the body after the `scraper = RedditScraper(...)` block with:

```python
    active_requests = 0
    max_active_requests = 0

    async def delayed_payload(*, client, path, params):
        nonlocal active_requests, max_active_requests
        active_requests += 1
        max_active_requests = max(max_active_requests, active_requests)
        await asyncio.sleep(0.05)
        active_requests -= 1
        return {"data": {"children": []}}

    with patch.object(scraper, "_request_oauth_json", side_effect=delayed_payload):
        posts = await scraper._fetch_oauth_json("python", limit=30)

    assert posts == []
    assert max_active_requests == 3
```

- [ ] **Step 5: Run the focused scraper concurrency tests**

Run:

```powershell
pytest tests/test_scraper.py::test_fetch_public_json_requests_feeds_concurrently tests/test_scraper.py::test_fetch_oauth_json_requests_feeds_concurrently -q
```

Expected after the fix:

```text
2 passed
```

- [ ] **Step 6: Run the full scraper suite**

Run:

```powershell
pytest tests/test_scraper.py -q
```

Expected:

```text
all tests in tests/test_scraper.py pass
```

- [ ] **Step 7: Commit the scraper test fix**

Run:

```powershell
git add -- tests/test_scraper.py
git commit -m "test: make scraper concurrency checks deterministic"
```

Expected:

```text
[main <hash>] test: make scraper concurrency checks deterministic
```

## Task 3: Pin Pytest Asyncio Loop Scope

**Files:**
- Modify: `pytest.ini`
- Test: full pytest warning output

- [ ] **Step 1: Update pytest configuration**

Replace `pytest.ini` with:

```ini
[pytest]
asyncio_mode = auto
asyncio_default_fixture_loop_scope = function
```

- [ ] **Step 2: Run a small async test sample**

Run:

```powershell
pytest tests/test_budget.py tests/test_scheduler.py -q
```

Expected:

```text
all selected tests pass
```

The previous `PytestDeprecationWarning` about `asyncio_default_fixture_loop_scope` should no longer appear.

- [ ] **Step 3: Commit the pytest config update**

Run:

```powershell
git add -- pytest.ini
git commit -m "test: pin pytest asyncio fixture loop scope"
```

Expected:

```text
[main <hash>] test: pin pytest asyncio fixture loop scope
```

## Task 4: Run Baseline Quality Gates

**Files:**
- No code files modified.
- Create later in Task 5: `docs/reports/2026-06-22-baseline-recovery.md`

- [ ] **Step 1: Run lint**

Run:

```powershell
ruff check .
```

Expected:

```text
All checks passed!
```

- [ ] **Step 2: Run focused repaired tests together**

Run:

```powershell
pytest tests/test_eval_harness.py::test_run_eval_offline_writes_artifacts tests/test_scraper.py::test_fetch_public_json_requests_feeds_concurrently tests/test_scraper.py::test_fetch_oauth_json_requests_feeds_concurrently -q
```

Expected:

```text
3 passed
```

- [ ] **Step 3: Run full pytest coverage gate**

Run:

```powershell
pytest --cov=. --cov-fail-under=80 -q
```

Expected:

```text
0 failed
Required test coverage of 80% reached.
```

Record the exact passed count, duration, and total coverage for Task 5.

- [ ] **Step 4: Run the project mypy gate with a longer timeout**

Run:

```powershell
mypy db.py scraper.py openrouter.py classifier.py pipeline.py bot.py scheduler.py export_sheets.py main.py
```

Expected success case:

```text
Success: no issues found
```

If it still does not complete in a reasonable local timeout, do not edit mypy settings in this task. Record the command, timeout value, and any partial output in Task 5 as a known validation status.

## Task 5: Record Baseline Recovery Report

**Files:**
- Create: `docs/reports/2026-06-22-baseline-recovery.md`

- [ ] **Step 1: Create the reports directory**

Run:

```powershell
New-Item -ItemType Directory -Force -Path 'docs\reports' | Out-Null
```

Expected:

```text
no output
```

- [ ] **Step 2: Write the baseline report**

Create `docs/reports/2026-06-22-baseline-recovery.md` with this structure, filling command results with the exact outputs observed in Task 4:

```markdown
# Baseline Recovery Report - 2026-06-22

## Scope

This report records the Phase 0 baseline recovery for `main`.

## Changes

- Made the offline eval CLI test resolve `eval/run_eval.py` from the local checkout.
- Replaced scraper concurrency wall-clock assertions with deterministic in-flight request counting.
- Pinned `pytest-asyncio` fixture loop scope to `function`.

## Validation

| Gate | Command | Result |
| --- | --- | --- |
| Lint | `ruff check .` | PASS: All checks passed. |
| Focused repaired tests | `pytest tests/test_eval_harness.py::test_run_eval_offline_writes_artifacts tests/test_scraper.py::test_fetch_public_json_requests_feeds_concurrently tests/test_scraper.py::test_fetch_oauth_json_requests_feeds_concurrently -q` | PASS: 3 passed. |
| Full pytest coverage | `pytest --cov=. --cov-fail-under=80 -q` | PASS: record the exact passed count, duration, and coverage emitted by the local run. |
| Mypy | `mypy db.py scraper.py openrouter.py classifier.py pipeline.py bot.py scheduler.py export_sheets.py main.py` | Record the exact local success output or timeout status from the local run. |

## Residual Risk

- This phase does not integrate hardening or product/eval changes from side branches.
- If mypy does not complete, a follow-up task must diagnose type-check performance or configuration.
- The full test suite can still reveal environment-specific failures on other machines; CI must remain the final shared check.

## Next Step

Proceed to a hardening intake inventory for `codex/autonomous-audit-fixes` after reviewing this baseline report.
```

Do not commit the report until the two validation result rows contain concrete local results from Task 4.

- [ ] **Step 3: Scan for unfinished report markers**

Run:

```powershell
$patterns = @('TB' + 'D', 'TO' + 'DO', 'FIX' + 'ME')
Select-String -Path 'docs\reports\2026-06-22-baseline-recovery.md' -Pattern $patterns
```

Expected:

```text
no output
```

- [ ] **Step 4: Commit the baseline report**

Run:

```powershell
git add -- docs/reports/2026-06-22-baseline-recovery.md
git commit -m "docs: record baseline recovery"
```

Expected:

```text
[main <hash>] docs: record baseline recovery
```

## Task 6: Final Phase 0 Cleanliness Check

**Files:**
- No new file changes expected.

- [ ] **Step 1: Check git status**

Run:

```powershell
git status --short
```

Expected:

```text
no output
```

- [ ] **Step 2: Review the Phase 0 commit stack**

Run:

```powershell
git log --oneline -5
```

Expected:

```text
<hash> docs: record baseline recovery
<hash> test: pin pytest asyncio fixture loop scope
<hash> test: make scraper concurrency checks deterministic
<hash> test: make eval runner path portable
<hash> docs: add pain finder stabilize integration design
```

- [ ] **Step 3: Confirm the next plan boundary**

Do not start hardening integration in this task. The next plan should be `2026-06-22-hardening-intake-inventory.md` and should inventory `codex/autonomous-audit-fixes` by invariant before any runtime code is ported.
