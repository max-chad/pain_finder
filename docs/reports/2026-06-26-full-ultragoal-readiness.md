# Full Ultragoal Readiness Report - 2026-06-26

## Scope

Branch: `codex/full-ultragoal-hardening`

This report closes the durable ultragoal run for `pain_finder`. The work started from the green `codex/baseline-recovery` branch, merged the runtime-hardening branch, and rewrote the highest-value product/eval pieces from the external review branch into smaller tested modules.

This is a local repository readiness report. It is not a production deployment certification.

## Proven Facts

- The branch was created from `codex/baseline-recovery`.
- Baseline recovery documents remain present:
  - `docs/reports/2026-06-22-baseline-recovery.md`
  - `docs/superpowers/plans/2026-06-22-baseline-recovery.md`
- `codex/autonomous-audit-fixes` was integrated with a no-fast-forward merge commit: `dbe47ee`.
- The merge conflict in `tests/test_scraper.py` was resolved without dropping the deterministic active-request concurrency assertions.
- Scratch artifact `AGENT_NOTES.md` from the source branch was not kept.
- Product/eval work from `bot/277606-external-review-plan` was not wholesale-merged because a merge-tree probe showed broad conflicts across README, runtime modules, eval files, export, digest, and tests.
- A smaller product/eval slice was implemented and committed as `444b03f`:
  - deterministic evidence verification;
  - hard-negative taxonomy;
  - fail-closed promotion metadata and score cap;
  - eval label/metric expansion;
  - Telegram feedback events;
  - research-friendly export fields;
  - deterministic buyer/WTP and competitor-radar helpers;
  - advisory score calibration artifact writer.
- Database evolution stayed additive-only through new tables/columns/indexes.
- No new paid production services or hidden network calls were added.

## Source-Branch Disposition

Accepted from `codex/autonomous-audit-fixes`:

- strict config validation;
- budget/resume accounting;
- bounded provider responses;
- source smoke and Docker healthcheck surfaces;
- URL/export path safety;
- additive stale migration repair;
- digest and callback resilience;
- Docker/CI safety guards.

Accepted as smaller rewrites from `bot/277606-external-review-plan`:

- `evidence.py`;
- `rejected_noise.py`;
- eval schema/labels/metrics for evidence and hard negatives;
- promotion metadata in `pipeline.py`;
- feedback storage and Telegram callbacks;
- export fields for `hard_negative_type` and `verified_evidence_count`;
- `buyer_intelligence.py`;
- `competitor_radar.py`;
- `eval/calibrate_score.py`.

Deferred or rejected:

- wholesale merge of `bot/277606-external-review-plan`, rejected because conflicts were too broad for a safe integration pass;
- static report builder and research-action workflow, deferred until evidence/promotion fields are stable in real operator use;
- broad cluster-first report rewrites, deferred because they touch shared analytics/digest behavior beyond the tested slice;
- old April report artifacts, rejected as current evidence because they are stale;
- new paid production services, hidden background calls, or unaudited dependency additions.

## Validation Evidence Already Collected

Focused hardening checks:

- `pytest tests/test_scraper.py -q` -> `50 passed in 26.58s`
- `pytest tests/test_config.py tests/test_healthcheck.py tests/test_main.py -q` -> `36 passed in 44.65s`
- `pytest tests/test_budget.py tests/test_openrouter.py tests/test_dspy_parser.py tests/test_embedder.py tests/test_clusterer.py -q` -> `75 passed in 69.11s`
- `pytest tests/test_db.py tests/test_pipeline.py tests/test_scheduler.py tests/test_digest_delivery.py tests/test_bot.py tests/test_export_sheets.py tests/test_url_safety.py -q` -> `185 passed in 44.71s`
- `pytest tests/test_smoke_collect.py tests/test_scraper_hn.py tests/test_scraper_reviews.py tests/test_eval_harness.py -q` -> `53 passed in 8.00s`
- `docker compose config -q` -> passed

Focused product/eval checks:

- `pytest tests/test_evidence.py tests/test_rejected_noise.py tests/test_buyer_intelligence.py tests/test_competitor_radar.py tests/test_score_calibration.py -q` -> `11 passed in 0.77s`
- `pytest tests/test_classifier.py tests/test_pipeline.py tests/test_eval_harness.py tests/test_db.py tests/test_digest_delivery.py tests/test_export_sheets.py tests/test_bot.py -q` -> `195 passed in 9.14s`
- `pytest tests/test_evidence.py tests/test_rejected_noise.py tests/test_buyer_intelligence.py tests/test_competitor_radar.py tests/test_score_calibration.py tests/test_classifier.py tests/test_pipeline.py tests/test_eval_harness.py tests/test_db.py tests/test_digest_delivery.py tests/test_export_sheets.py tests/test_bot.py -q` -> `206 passed in 9.04s`
- `ruff check .` -> passed before this report was written

Final gate status is recorded below.

## Final Gate Results

Required local gates:

- `ruff check .` -> passed
- `mypy db.py scraper.py openrouter.py classifier.py pipeline.py bot.py scheduler.py export_sheets.py main.py` -> passed, `Success: no issues found in 9 source files`
- `pytest --cov=. --cov-fail-under=80 -q` -> passed, `441 passed`, total coverage `91.93%`
- `docker compose config -q` -> passed
- `python -m pip_audit -r requirements.txt` -> passed, `No known vulnerabilities found`
- `python eval/run_eval.py --help` -> passed
- `python eval/calibrate_score.py --help` -> passed
- `git diff --check` -> passed, with only LF-to-CRLF working-copy warnings for README/doc/test files
- Post-review fix gate: `pytest --cov=. --cov-fail-under=80 -q` -> passed, `442 passed`, total coverage `91.93%`

Optional/local-environment checks:

- `python healthcheck.py --fail-on-job-errors` without local env -> failed on missing `TELEGRAM_BOT_TOKEN`
- `python healthcheck.py --fail-on-job-errors` with dummy local env -> failed on missing initialized database at `C:\Users\max_chad\Music\pain_finder\pain_finder.db`
- `python smoke_collect.py --source hn --hn-keyword "manual process" --limit 1 --require-posts` -> source reachable but zero posts for that narrow query
- `python smoke_collect.py --source hn --hn-keyword "python" --limit 1 --require-posts` -> passed with one HN preview row and no side effects

Cleanup and independent review:

- ai-slop-cleaner pass -> passed, no-op cleanup
  - Scope: files changed from `codex/baseline-recovery...HEAD`
  - Behavior lock: full local gate already green before cleaner
  - Findings: `fallback` and `workaround` occurrences were classified as domain evidence, tested compatibility/fail-safe behavior, usage accounting metadata, or test mocks
  - Masking fallback slop: none found
  - Post-cleaner verification: `ruff check .` passed; `mypy ...` passed; `git diff --check` passed with only LF-to-CRLF warnings; `pytest --cov=. --cov-fail-under=80 -q` passed with `441 passed`, coverage `91.93%`
- independent `code-reviewer` and `architect` review -> passed after fixes
  - Initial code-reviewer result: `REQUEST CHANGES` for legacy `triage:favorite:reddit:abc123` callback parsing, plus docs label guidance drift
  - Fix: commit `4d3bc0c` preserves source-prefixed legacy triage callback IDs, adds regression coverage, corrects `evidence_quality=exact_quote`, corrects `evidence_rejection_reason`, and discloses callback/session tradeoffs
  - Re-check: code-reviewer `APPROVE`; architect `CLEAR`

## Residual Risks

- Local tests do not prove Telegram production delivery, Google Sheets credentials, Reddit/HN/review-source availability, or deployment environment health.
- Telegram list/card inline callbacks are backed by in-memory session tokens for long callback payloads; they expire after 24 hours or process restart. Legacy direct post-id callbacks remain supported.
- Promotion/evidence metadata is currently written by `pipeline.py` and decoded by downstream export/digest/radar surfaces. The implemented slice is tested, but broader future product surfaces should centralize row-level decoding before expanding this contract.
- `python healthcheck.py --fail-on-job-errors` depends on the target environment and database state.
- Source smoke checks are intentionally read-only but still depend on external network/source behavior.
- Advisory calibration output is not an accepted runtime scoring change and uses its own review vocabulary until a later explicit scoring change aligns it with runtime scoring.
- Static report-builder and research-action workflows remain deferred.

## Verdict

Locally, the branch is materially stronger than baseline: runtime safety, budget handling, provider bounds, source health surfaces, evidence-gated promotion metadata, feedback capture, eval metrics, and exports are all covered by focused tests.

The branch should be treated as ready for PR/review after final local gates pass. It should not be treated as production-ready until deployment-specific healthcheck, source smoke, Telegram delivery, and operator acceptance are run in the target environment.
