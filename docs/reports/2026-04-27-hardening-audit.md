# Pain Finder Hardening Audit — 2026-04-27

Wave 9.1–9.3 audit for the external-review synthesis branch. This document is intentionally conservative: it records what is verified in the current PR, adds the Wave 9.2 threshold/manifest handoff, and states what is still not proven enough for unattended production use.

## Branch / PR scope

- Repository: `max-chad/pain_finder`.
- Branch: `bot/277606-external-review-plan`.
- PR #6: `https://github.com/max-chad/pain_finder/pull/6`.
- PR state at audit start: open and draft.
- Base branch: `main`.
- Audited head before this Wave 9 documentation slice: `e1e46b8 feat: add Wave 8 research action workflow`.
- Wave 9.2 threshold-assessment head before this traceability slice: `e3327c8 feat: add Wave 9 MVP threshold assessment`.
- Current PR state for the Wave 9.3 handoff: PR #6 remains open and draft; this branch stacks follow-up commits into the same PR.
- Scope: branch/PR work only; this audit does not claim the same state is already merged to `main`.

## Validation evidence

Latest branch validation evidence before this Wave 9 documentation/test slice:

| Gate | Command | Result |
| --- | --- | --- |
| Focused Wave 8.4 stale-guard tests | `pytest -q tests/test_pipeline.py::test_generate_digest_adds_evidence_gated_research_actions_to_top_clusters tests/test_pipeline.py::test_attach_research_actions_sorts_digest_clusters_by_row_grounded_eligible_score tests/test_digest_delivery.py::test_daily_digest_document_renders_rich_cluster_cards_as_primary_surface tests/test_digest_delivery.py::test_daily_digest_document_fetches_all_promoted_clusters_before_eligible_sorting tests/test_report_builder.py::test_research_report_renders_required_static_sections_from_fixture_data` | `5 passed` |
| Focused Wave 8.4 suites | `pytest -q tests/test_openrouter.py tests/test_pipeline.py tests/test_report_builder.py tests/test_digest_delivery.py tests/test_db.py tests/test_clusterer.py` | `137 passed` |
| Full regression | `pytest --cov=. --cov-fail-under=80 -q` | `343 passed`, coverage `90.28%` |
| Lint | `ruff check .` | passed |
| Syntax | `python -m compileall -q openrouter.py research_actions.py pipeline.py clusterer.py db.py report_builder.py digest_delivery.py tests` | passed |
| Whitespace diff check | `git diff --check` | passed |
| Compose config | `timeout 45s docker compose --ansi never -f docker-compose.yml config --quiet` | passed |
| static added-lines secret scan | local added-line scanner over staged diff | `0 findings` |
| GitHub Actions | `gh pr checks 6` | `quality` passed on PR head `e1e46b8` |
| Independent review | parallel staged-diff reviews over Wave 8.4 | no blocking evidence-gating/security issues after fixes |

Final Wave 9 documentation/hardening rerun for this slice:

| Gate | Command | Result |
| --- | --- | --- |
| Focused Wave 9 docs/eval/report surfaces | `pytest -q tests/test_hardening_audit_report.py tests/test_eval_harness.py tests/test_report_builder.py tests/test_digest_delivery.py` | `38 passed in 1.12s` |
| Lint | `ruff check .` | passed |
| Syntax | `python -m compileall -q .` | passed |
| Whitespace diff check | `git diff --check` | passed |
| Compose config | `timeout 45s docker compose --ansi never -f docker-compose.yml config --quiet` | passed |
| static added-lines secret scan | local added-line scanner over staged+unstaged diff | `0 findings` |
| Full regression | `pytest --cov=. --cov-fail-under=80 -q` | `345 passed`, total coverage `90.30%` |

Final Wave 9.3 traceability/release-readiness validation for this slice:

| Gate | Command | Result |
| --- | --- | --- |
| Focused Wave 9.3 manifest/docs suite | `pytest -q tests/test_eval_harness.py tests/test_hardening_audit_report.py` | `27 passed in 0.36s` |
| Full regression | `pytest --cov=. --cov-fail-under=80 -q` | `352 passed`, total coverage `90.41%` |
| Lint | `ruff check .` | passed |
| Syntax | `python -m compileall -q .` | passed |
| Whitespace diff check | `git diff --check` | passed |
| Compose config | `timeout 45s docker compose --ansi never -f docker-compose.yml config --quiet` | passed |
| static added-lines secret scan | local added-line scanner over unstaged diff | `0 findings` |
| Independent review | unstaged-diff review of Wave 9.3 manifest/readiness packet | pass; no blocking issues |

## Evaluation / MVP threshold status

The checked-in eval harness is present and covers evidence, hard negatives, cluster/usefulness metrics, and baseline comparison. However, the branch should **not** be considered fully usable for unattended production use until the MVP thresholds are measured on a larger live/offline benchmark or explicitly waived by the user.

Current status against Wave 9.2 MVP gates:

| MVP metric | Target | Current audit status |
| --- | ---: | --- |
| Pain precision | >= 0.75 | Not release-proven in this audit; checked-in seed set is still a starter benchmark. |
| Pain recall | >= 0.60 | Not release-proven in this audit; high-recall behavior needs a larger labeled run. |
| Evidence exact match | >= 0.95 | Evidence verifier and exact-match metrics exist; target not claimed without a fresh benchmark artifact. |
| Monetizable precision | >= 0.65 | Not release-proven in this audit; buyer/WTP signals are implemented but need benchmark confirmation. |
| Top-10 useful insight rate | >= 0.50 | Metric support exists through `top_n_useful_rate`; insufficient feedback labels for a release claim. |
| Cluster duplicate rate | <= 0.20 | Metric support exists through cluster labels; not release-proven on a large cluster benchmark. |

Decision: the PR is acceptable as a draft research-system improvement, but not ready for unattended production use. It is suitable for analyst-controlled self-research runs with evidence inspection. Wave 9.2 threshold status is an eval/audit gate only, not a production-readiness claim.

Wave 9.3 traceability handoff: `eval/run_eval.py` writes both `mvp_thresholds.json` and `run_manifest.json`. The manifest links dataset/label inputs, prediction/metrics/threshold artifacts, dataset size, `reference_now_ts`, and the threshold summary with `readiness_scope=eval_audit_gate_only` and `production_ready_claimed=false`.

## Evidence-first safety audit

Evidence-first behavior is the main safety invariant for this branch.

Verified in code/tests across Waves 2-8:

- `evidence.py` performs deterministic quote verification and stores match type/confidence.
- `verified_evidence_json`, `evidence_quality`, `evidence_match_rate`, `confidence`, `uncertainty_reason`, and `needs_human_review` are persisted additively.
- Promotion surfaces require verified evidence and first-hand/buyer authority signals.
- No verified quote means the item goes to weak/Needs Review or diagnostic surfaces, not Top Opportunities.
- Rejected/noise examples are bounded diagnostics, not a promotion path.
- Feedback metadata is diagnostic/manual-review data and does not promote weak/no-evidence rows.
- Competitor radar, source diversity, buyer/WTP intelligence, and research actions are all gated by promotion eligibility and verified evidence.
- Wave 8.4 hardening fixed stale `representative_examples` leakage: report/digest/research-action text is rebuilt from current eligible DB rows, and stale persona/workaround/incumbent fields are not copied into primary surfaces.
- OpenRouter research-action payloads must include anchored `evidence_post_ids`; malformed or unanchored action payloads fail closed.

Residual risk: evidence quality is only as good as source availability and quote extraction. Deletions/removed posts remain handled as data-quality signals, not as proof of opportunity.

## SQLite migration audit

- `db.py` uses additive migration helpers (`ALTER TABLE ... ADD COLUMN`) and table creation.
- Search for destructive migration patterns found no `DROP TABLE`, `DROP COLUMN`, or `RENAME COLUMN` migration path in `db.py`.
- Wave 8.4 added `research_action_json TEXT DEFAULT '{}'` additively.
- Backward compatibility is preserved through JSON decoder aliases and default values.

Residual risk: production DB backups are still operational responsibility outside this PR.

## Report/export surface audit

Implemented analyst-facing surfaces:

- grouped `.docx` digest with verified canonical cluster cards;
- local static HTML report;
- CSV/Google Sheets research export fields;
- rejected/noise diagnostics;
- feedback export for label review;
- competitor failure radar;
- multi-source/source-diversity diagnostics;
- buyer/WTP intelligence;
- concise `Next research action` block for eligible clusters only.

Primary surfaces are evidence-first: mixed clusters are filtered to eligible evidence-backed members before rendering; all-weak/no-evidence rows remain outside primary promotion surfaces.

## Runtime guardrails and source coverage

Checked-in `config.py` defaults relevant to fail-safe operation:

- `CLASSIFIER_MODE='dual'`.
- `SCREEN_MIN_RULE_SCORE=1` for high-recall deterministic prescreening.
- `DSPY_REDDIT_PARSER_ENABLED=True` unless explicitly disabled by environment.
- `DAILY_BUDGET_USD=2.0`.
- `LLM_MAX_CLASSIFICATIONS_PER_RUN=0`, meaning the per-run classification cap is disabled by default; runtime budget still applies.
- `SCREEN_MAX_LLM_CANDIDATES_PER_RUN` defaults to `LLM_MAX_CLASSIFICATIONS_PER_RUN`, so it is also uncapped when that value is `0`.
- `TREND_LOOKBACK_DAYS=30`, `TREND_MIN_CLUSTER_SIZE=3`, `TREND_CLUSTER_SIMILARITY=0.72`.
- `DEEP_DIVE_WTP_THRESHOLD=8`, `DEEP_DIVE_MAX_COMMENTS=250`.
- `SCRAPER_TOP_COMMENTS=5`, `SCRAPER_COMMENT_FETCH_CONCURRENCY=8`.
- `SEMANTIC_CANDIDATE_QUERIES` contains 5 configured query prototypes.

Effective values observed in the local audit environment were stricter for several knobs (`DSPY_REDDIT_PARSER_ENABLED=False`, `LLM_MAX_CLASSIFICATIONS_PER_RUN=10`, `SCREEN_MAX_LLM_CANDIDATES_PER_RUN=10`, `DEEP_DIVE_WTP_THRESHOLD=10`, `SCRAPER_TOP_COMMENTS=0`). Those are local environment overrides, not checked-in defaults, and must not be treated as guarantees after deploy.

Coverage/quality surfaces exist through ingestion coverage tables, report confidence blocks, and source-diversity/triangulation fields. The remaining hardening need is operational: set explicit per-run caps for unattended runs, collect fresh runs, and compare actual coverage/failure rates over time.

## Secrets/static scan

- No real credentials are documented here.
- Secrets/config values inspected during implementation must remain redacted as `[REDACTED]` if referenced externally.
- Latest static added-lines secret scan before this docs slice reported `0 findings`.
- Tests use placeholder values like `key`; avoid secret-like placeholders such as `test-key`.

## Open risks / release decision

Release decision for PR #6 at this audit point:

- ✅ Keep PR #6 as draft.
- ✅ Safe to continue analyst-controlled self-research / simulation runs from the branch after final validation.
- ⚠️ Not ready for unattended production use until a larger benchmark or explicit user waiver covers Wave 9.2 thresholds.
- ⚠️ Need fresh eval artifact before claiming pain precision, pain recall, monetizable precision, evidence exact-match target, Top-10 usefulness, or cluster duplicate-rate targets.
- ⚠️ Need ongoing runtime monitoring of source coverage, deletion/body availability, LLM invalid-output rates, and budget pauses.

Recommended next step after merge/review: run a fresh labeled eval pass, archive `metrics.json`, `mvp_thresholds.json`, and `run_manifest.json` under an ignored artifact path, and manually copy the threshold summary into a dated report before enabling larger autonomous runs.
