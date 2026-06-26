# Full Ultragoal Intake Report - 2026-06-26

## Scope

This report inventories the two existing source branches for the full `pain_finder` hardening program:

- Hardening branch: `codex/autonomous-audit-fixes` at `03e10b2`.
- Product/eval branch: `bot/277606-external-review-plan` at `7f4af5c`.

The current target branch is `codex/full-ultragoal-hardening`, based on the green Phase 0 baseline from `codex/baseline-recovery`.

## Method

- Reviewed branch logs and diff stats.
- Ran read-only merge feasibility checks with `git merge-tree --write-tree --name-only --messages`.
- Compared branch file sets with `git diff --name-only`.
- Used independent inventory agents for hardening and product/eval grouping.

## Merge Feasibility

Hardening branch:

- `git merge-tree --write-tree --name-only --messages HEAD codex/autonomous-audit-fixes` reports a content conflict in `tests/test_scraper.py`.
- `requirements.txt` and `tests/test_eval_harness.py` auto-merge but require manual review.
- Do not wholesale merge. The branch contains valuable hardening, but also broad docs/metadata churn and dependency policy changes that must be reconciled with the Phase 0 baseline.

Product/eval branch:

- `git merge-tree --write-tree --name-only --messages HEAD bot/277606-external-review-plan` reports no textual conflicts against the Phase 0 baseline.
- The main risk is semantic churn: schema, scoring, report rendering, and provider contracts change together.
- Do not treat old April reports as current validation evidence.

## Hardening Intake

| Group | Status | Representative commits/files | Rationale | Validation |
| --- | --- | --- | --- | --- |
| Runtime safety and config validation | integrate now | `95f685c`, `1dd2624`, `5baed81`, `b8d7eb5`, `151d59b`; `config.py`, `healthcheck.py`, `.env.example`, `main.py`, `tests/test_config.py`, `tests/test_healthcheck.py` | Fail-fast runtime validation and local healthcheck reduce bad deploy states. | `pytest tests/test_config.py tests/test_healthcheck.py tests/test_main.py -q` |
| Budget, resume, and usage accounting | integrate now | `e2a70b2`, `7b9904f`, `31efcb4`, `85a3fd3`, `9361569`; `budget.py`, `pipeline.py`, `openrouter.py`, `dspy_parser.py`, `eval/run_eval.py` | Budget controls are a core safety invariant. | `pytest tests/test_budget.py tests/test_pipeline.py tests/test_openrouter.py tests/test_dspy_parser.py tests/test_eval_harness.py -q` |
| Provider parsing and response bounds | integrate now | `61fdc6a`, `75fbfc4`, `343d6ab`, `13caf51`, `6959bc8`, `d913fbe`; `openrouter.py`, `dspy_parser.py`, `embedder.py`, `clusterer.py` | Prevents unbounded reads, malformed payload persistence, and provider drift crashes. | `pytest tests/test_openrouter.py tests/test_dspy_parser.py tests/test_embedder.py tests/test_clusterer.py -q` |
| Source smoke and health tooling | integrate now | `b1ae79d`, `7008ded`, `b5a312f`, `dc129cc`, `90fa5d9`; `smoke_collect.py`, `healthcheck.py`, `scraper*.py`, `url_safety.py` | Gives local, read-only checks for source readiness and failure surfacing. | `pytest tests/test_smoke_collect.py tests/test_healthcheck.py tests/test_scraper.py tests/test_scraper_hn.py tests/test_scraper_reviews.py tests/test_url_safety.py -q` |
| URL, export, and report path safety | integrate now | `03e10b2`, `d70c4fb`, `6d91e70`, `7394058`, `abfa74d`, `a8026ec`; `url_safety.py`, `bot.py`, `export_sheets.py`, `pipeline.py`, `scraper_reviews.py` | Protects file-send and scrape targets from path/host boundary mistakes. | `pytest tests/test_url_safety.py tests/test_export_sheets.py tests/test_bot.py tests/test_pipeline.py tests/test_scraper_reviews.py -q` |
| Migration and persistence safety | integrate now | `e55f0fc`, `fa6e328`, `02fafad`, `2f9463e`, `64a5f95`, `d96ee94`; `db.py`, `pipeline.py`, `scheduler.py`, `clusterer.py` | Additive stale-migration repair and rollback behavior protect existing SQLite data. | `pytest tests/test_db.py tests/test_pipeline.py tests/test_scheduler.py tests/test_clusterer.py -q` |
| Digest and operator resilience | integrate now | `0e81f0b`, `20fac9b`, `f04e53a`, `84f3c8d`, `a509d89`, `343deb3`; `digest_delivery.py`, `bot.py`, `scheduler.py`, `pipeline.py` | Operator flows should degrade gracefully on malformed rows and stale callbacks. | `pytest tests/test_digest_delivery.py tests/test_bot.py tests/test_scheduler.py tests/test_pipeline.py -q` |
| Docker and CI safety | rewrite smaller | `861dcca`, `723f952`, `65868cd`, `561aa5f`, `f904511`; `.dockerignore`, `.gitignore`, `Dockerfile`, `docker-compose.yml`, `.github/workflows/test.yml`, `requirements*.txt` | Keep useful safety guards, but do not accept dependency-floor regressions or optional DSPy policy changes blindly. | `docker compose config -q`; `ruff check .`; project mypy gate |
| Eval/test support | integrate now for tests, reject metadata churn | `9361569`, `5f4e715`, `7e94701`; `eval/run_eval.py`, `tests/test_eval_harness.py`, health/smoke/url tests | Keep regression coverage and live-spend protection. Avoid stale notes as current evidence. | `pytest tests/test_eval_harness.py tests/test_healthcheck.py tests/test_smoke_collect.py tests/test_url_safety.py -q` |

Hardening items to reject or defer:

- Reject deletion or replacement of current June baseline docs.
- Defer large `AGENT_NOTES.md` import; it is not needed for runtime behavior.
- Do not lower `pytest-asyncio>=0.24` or weaken the explicit fixture loop scope.
- Do not accept old optional-DSPy dependency policy without revalidating current runtime expectations.

## Product And Eval Intake

| Group | Status | Representative commits/files | Rationale | Validation |
| --- | --- | --- | --- | --- |
| Deterministic evidence verifier | integrate now | `0a4e528`, `e693367`; `evidence.py`, `classifier.py`, `db.py`, `pipeline.py`, `tests/test_evidence.py` | Exact source anchoring is the foundation for fail-closed promotion. | `pytest tests/test_evidence.py tests/test_classifier.py tests/test_pipeline.py -q` |
| Hard-negative rejected-noise taxonomy | integrate now | `9746cad`, `1b70f19`; `rejected_noise.py`, `eval/label_guide.md`, `eval/labels.schema.json`, `digest_delivery.py`, `report_builder.py` | Founder pitches, advice, news, B2C noise, and stale/solved items must be measurable hard negatives. | `pytest tests/test_eval_harness.py tests/test_digest_delivery.py -q` |
| Fail-closed promotion eligibility | integrate now | `ef56af6`, `e693367`, `1b70f19`; `pipeline.py`, `classifier.py`, `digest_delivery.py`, `db.py` | Promotion should require verified evidence, buyer authority, and no hard-negative flags. | `pytest tests/test_pipeline.py tests/test_digest_delivery.py tests/test_db.py -q` |
| Eval schema, labels, and metrics expansion | integrate now | `9746cad`, `9902872`, `c6bc5a2`; `eval_harness.py`, `eval/run_eval.py`, `eval/labels*.jsonl`, `eval/README.md` | Needed to measure evidence and hard-negative behavior. | `pytest tests/test_eval_harness.py -q`; `python eval/run_eval.py --help` |
| Staged pain/evidence gates | rewrite smaller | `7fb3edc`, `9dc9eda`, `7f4af5c`; `openrouter.py`, `classifier.py`, `config.py`, `main.py` | Valuable but broad provider/prompt contract change; keep default-off or narrowly port after provider hardening is stable. | `pytest tests/test_openrouter.py tests/test_classifier.py tests/test_config.py tests/test_main.py -q` |
| Feedback loop | integrate now | `2943430`; `feedback.py`, `bot.py`, `db.py`, `eval_harness.py` | Feedback actions become future labels and keep operator judgement in the loop. | `pytest tests/test_bot.py tests/test_db.py tests/test_eval_harness.py -q` |
| Static research reports and research actions | defer | `2c00b5a`, `e1e46b8`, `532d223`; `report_builder.py`, `research_actions.py`, old April docs | Useful, but depends on accepted evidence/cluster fields and contains stale report artifacts. | Defer until core evidence/promotion tests pass. |
| Buyer intelligence | integrate now after evidence gate | `313013f`; `buyer_intelligence.py`, `digest_delivery.py`, `report_builder.py` | Adds buyer/WTP signal only when verified rows survive the gate. | `pytest tests/test_buyer_intelligence.py tests/test_digest_delivery.py -q` |
| Competitor failure radar | integrate now after evidence gate | `df08a50`; `competitor_radar.py`, `clusterer.py`, `db.py`, `digest_delivery.py` | Useful opportunity signal if evidence-gated. | `pytest tests/test_competitor_radar.py tests/test_db.py tests/test_digest_delivery.py -q` |
| Cluster and digest improvements | rewrite smaller | `80c0c1f`, `ab1aa25`, `de920cd`; `clusterer.py`, `digest_delivery.py`, `db.py`, `embedder.py`, `pipeline.py` | Large semantic surface; port only stable cluster foundations and bounded rendering after core promotion rules are green. | `pytest tests/test_clusterer.py tests/test_digest_delivery.py tests/test_pipeline.py -q` |
| Research-friendly export fields | integrate now | `7455758`, `e693367`; `export_sheets.py`, `db.py` | Additive export fields are useful if formula/path safety remains intact. | `pytest tests/test_export_sheets.py tests/test_db.py -q` |

Product/eval items to reject or defer:

- Defer old April hardening audit report as current proof.
- Defer broad report/research-action surfaces until evidence and fail-closed promotion are integrated.
- Rewrite staged LLM gates smaller; they touch provider behavior and should follow runtime provider hardening.

## Initial Integration Order

1. Merge or port hardening branch first, resolving the known `tests/test_scraper.py` conflict and preserving Phase 0 test fixes.
2. Run focused hardening suites and repair regressions.
3. Port product/eval evidence and fail-closed promotion slices.
4. Add product intelligence slices only where tests prove bounded behavior.
5. Update docs and readiness report.
6. Run final gates and independent review.

## Conflict Watchlist

- `tests/test_scraper.py`: real hardening merge conflict; preserve deterministic active-request overlap assertions and add malformed/bounds coverage from source.
- `requirements.txt`: preserve `pytest-asyncio>=0.24`; do not accept stale dependency floors.
- `tests/test_eval_harness.py`: preserve repo-relative `eval/run_eval.py` path.
- `docs/reports/2026-06-22-baseline-recovery.md` and `docs/superpowers/*`: preserve current June baseline artifacts.

## Required Final Gates

```powershell
ruff check .
mypy db.py scraper.py openrouter.py classifier.py pipeline.py bot.py scheduler.py export_sheets.py main.py
pytest --cov=. --cov-fail-under=80 -q
```

Optional, if tooling and local environment permit:

```powershell
docker compose config -q
python healthcheck.py --strict
python smoke_collect.py --source reddit --limit 1
```
