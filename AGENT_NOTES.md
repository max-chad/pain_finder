# AGENT_NOTES

## 2026-05-24 - Portable local baseline

- Reason: `pytest -q` failed locally on Windows even though the scraper implementation already used `asyncio.gather`; the concurrency tests measured wall-clock time including `httpx.AsyncClient` startup overhead instead of proving task overlap.
- Change: Replaced the scraper wall-clock assertions with deterministic in-flight request counting for public JSON and OAuth JSON feed fetches.
- Verification: Targeted scraper tests and full suite are run after this note.
- Impact: Improves local/CI compatibility and keeps the concurrency contract covered without machine-speed flakiness.

## 2026-05-24 - Eval runner path portability

- Reason: `tests/test_eval_harness.py::test_run_eval_offline_writes_artifacts` hardcoded `/opt/repos/pain_finder/eval/run_eval.py`, which fails outside the Linux CI checkout path.
- Change: Resolve `eval/run_eval.py` relative to the repository root inferred from the test file path.
- Verification: Targeted eval harness test and full suite are run after this note.
- Impact: Allows the offline eval CLI test to run from local Windows checkouts and alternate CI workspace paths.

## 2026-05-24 - Spreadsheet export injection guard

- Reason: exported rows contain untrusted Reddit/HN/review text, and CSV or Google Sheets cells beginning with `=`, `+`, `-`, or `@` can be interpreted as formulas when opened by spreadsheet tools.
- Change: Escape dangerous spreadsheet cell prefixes with a leading apostrophe for both CSV output and Google Sheets upsert values.
- Verification: Added targeted CSV and Google Sheets export tests covering dangerous title, summary, niche, and deep-dive fields.
- Impact: Reduces formula-injection risk when operators open exported pain reports.

## 2026-05-24 - Stable review ingestion identity

- Reason: review-source `post_id` values were based on the card index after parsing, so a new or reordered review page could change identifiers for existing complaints and create duplicates or overwrite identity.
- Change: Generate review IDs from a stable hash of site, product slug, URL, rating, and normalized review text; also apply `max_reviews` after filtering to negative reviews.
- Verification: Added tests proving stable IDs under page reordering and that positive reviews do not consume the negative-review limit.
- Impact: Improves review ingestion correctness and dedup reliability across repeated runs.

## 2026-05-24 - Explicit pytest asyncio loop scope

- Reason: pytest emitted a deprecation warning that the default async fixture loop scope will change in a future pytest-asyncio release.
- Change: Set `asyncio_default_fixture_loop_scope = function` explicitly in `pytest.ini`.
- Verification: Full test suite is run after this note.
- Impact: Keeps async test behavior stable across dependency upgrades and removes warning noise.

## 2026-05-24 - Stable local embedding buckets

- Reason: local hash-based fallback embeddings used Python `hash()`, which is randomized per process; persisted dedup vectors and macro cluster snapshots could become inconsistent after restart.
- Change: Use a stable `blake2b` token-to-bucket hash in `embedder.py` and `clusterer.py`.
- Verification: Added targeted tests for stable bucket mapping in fallback embeddings and macro clustering.
- Impact: Improves dedup and clustering reproducibility when remote embeddings or sentence-transformers are unavailable.

## 2026-05-24 - Optional DSPy dependency surface

- Reason: `pip-audit -r requirements.txt` reported `diskcache 5.6.3` / `CVE-2025-69872`, pulled transitively by `dspy`; DSPy is lazy-loaded and documented as an optional parser path, but was installed by the base requirements.
- Change: Move `dspy>=3.2` from `requirements.txt` to `requirements-dspy.txt` and document the optional install command.
- Verification: `pip-audit -r requirements.txt` and full quality gates are run after this note.
- Impact: Removes a vulnerable optional transitive dependency from default installs while preserving an explicit opt-in path for DSPy users.

## 2026-05-25 - DSPy parser is explicit opt-in

- Reason: after making DSPy an optional install, the parser flag still defaulted to enabled, so a base deployment with an LLM key would try the missing optional parser path before falling back.
- Change: Default `DSPY_REDDIT_PARSER_ENABLED` to off, update `.env.example` and README, and guard startup so an explicitly enabled parser is skipped once if the `dspy` package is not installed.
- Verification: Added config, startup, and availability tests for the opt-in behavior.
- Impact: Keeps default deployments on the supported base dependency set without per-post optional-dependency failures or noisy fallback logs.

## 2026-05-25 - Partial Reddit feed failure tolerance

- Reason: public JSON, OAuth JSON, and RSS ingestion used `asyncio.gather` over multiple Reddit feeds/searches; one failed endpoint could discard successful peer feed payloads or optional search results.
- Change: Treat individual feed/search failures independently, keep successful peer feeds, and still raise to the next fallback layer when every primary feed fails.
- Verification: Added tests for partial public JSON, OAuth JSON, RSS, and optional search failures.
- Impact: Improves data collection reliability under Reddit endpoint/rate-limit instability without hiding total source failure.

## 2026-05-25 - Docker SQLite data directory

- Reason: `docker-compose.yml` bind-mounted `./pain_finder.db` directly to `/app/pain_finder.db`; on a fresh host a missing bind source can be created as a directory, causing SQLite startup failures.
- Change: Mount `./data` to `/app/data`, set `DB_PATH=/app/data/pain_finder.db`, create `/app/data` in the image, ignore local data directories in Git/Docker build context, and make the `.env` file optional for Compose config validation.
- Verification: Docker Compose config validation is run after this note.
- Impact: Makes first-run Docker deployment more reliable and keeps persistent DB/report storage explicit.

## 2026-05-25 - CI dependency audit gate

- Reason: dependency CVE checks were run locally but were not part of the GitHub Actions quality gate, so future vulnerable default dependencies could regress silently.
- Change: Install `pip-audit` in CI and run `python -m pip_audit -r requirements.txt`; document the same command in README quality gates.
- Verification: Local `pip-audit` and workflow syntax/config checks are run after this note.
- Impact: Moves dependency security from an ad-hoc local check into the default CI path.

## 2026-05-25 - Local container healthcheck

- Reason: Docker deployments had no local health signal proving that required env parsing, SQLite storage, and report output paths are usable after startup.
- Change: Add `healthcheck.py`, wire it into the Dockerfile `HEALTHCHECK`, and document that it performs only local checks without external API calls.
- Verification: Added healthcheck tests, included `healthcheck.py` in documented/CI mypy checks, and run Docker Compose config validation plus full quality gates after this note.
- Impact: Improves deploy observability and catches broken volume/env/storage setups before data collection silently stalls.

## 2026-05-25 - Graceful runtime shutdown signals

- Reason: `main.run()` waited on an unreferenced `asyncio.Event`, so container `SIGTERM`/manual `SIGINT` had no application-level shutdown path before cleanup.
- Change: Add a signal-aware shutdown event for `SIGINT` and `SIGTERM`, and use it in both Telegram and Hermes runtime waits.
- Verification: Added a unit test proving signal handlers set the shutdown event; full gates are run after this note.
- Impact: Docker stops and manual interrupts can flow through Telegram stop, scheduler stop, and database close cleanup.

## 2026-05-25 - Explicit scheduler overlap policy

- Reason: long-running LLM ingestion jobs should not overlap or fan out after scheduler delays, and relying on APScheduler defaults makes that production invariant implicit.
- Change: Configure scheduler job defaults with `coalesce=True`, `max_instances=1`, and a 5-minute `misfire_grace_time`.
- Verification: Added a scheduler test asserting the effective job defaults on loaded monitor jobs; full gates are run after this note.
- Impact: Reduces duplicate collection/classification load and makes delayed job behavior predictable.

## 2026-05-25 - Read-only source collection smoke check

- Reason: deployments had a local healthcheck for env/storage but no safe way to prove Reddit, HN, and review-source collection paths before starting Telegram/scheduler flows or spending LLM budget.
- Change: Add `smoke_collect.py`, a JSON-emitting read-only CLI that fetches source posts only, avoids `config.py`'s Telegram/LLM fail-fast requirements, and supports `--require-posts` for stricter deployment gates.
- Verification: Added targeted smoke CLI tests for Reddit success, source exceptions, empty-source failure, and all-source review target handling; full gates are run after this note.
- Impact: Improves deploy readiness and diagnostics for data collection without database writes, Telegram side effects, scheduler startup, or LLM spend.

## 2026-05-25 - HN full-source failure is explicit

- Reason: HN ingestion tolerated partial keyword failures, but a total HTTP failure across every valid keyword returned an empty list and looked like a successful no-op to scheduler/smoke checks.
- Change: Track attempted, successful, and failed HN keyword queries; preserve partial-success behavior, but raise when every attempted query fails.
- Verification: Added a targeted HN scraper test for all-keyword HTTP failure; full gates are run after this note.
- Impact: Improves source outage observability and prevents full HN collection failures from being mistaken for no new data.

## 2026-05-25 - Review full-target failure is explicit

- Reason: review ingestion converted every HTTP fetch failure into an empty result, so a full review-source outage looked identical to accessible pages with no negative reviews.
- Change: Raise `ReviewFetchError` for target HTTP failures, keep partial target success in `fetch_many_targets`, and raise only when every enabled target fails.
- Verification: Added targeted review scraper tests for partial target failure and all-target failure; full gates are run after this note.
- Impact: Improves scheduled review ingestion diagnostics while preserving valid empty accessible pages as no-op results.

## 2026-05-25 - LLM cache keys include generation config

- Reason: LLM response cache keys included provider/model/path/reasoning but omitted temperature and used only explicit per-call max output tokens, so changing `LLM_TEMPERATURE` or global `LLM_MAX_TOKENS` could reuse stale payloads generated under different runtime settings.
- Change: Include temperature and the effective token limit in the cache fingerprint.
- Verification: Added a targeted cache-key test covering temperature and token-limit differences; full gates are run after this note.
- Impact: Prevents config changes from silently reusing incompatible cached LLM responses during collection, deep dives, clustering, and GTM generation.

## 2026-05-25 - Runtime enum env fails fast

- Reason: invalid `APP_MODE`, `CLASSIFIER_MODE`, or `DIGEST_GROUP_BY` values could silently fall back or be treated as a different runtime path, including disabling Telegram polling for an `APP_MODE` typo.
- Change: Validate those documented enum environment variables during config import and raise a clear `ValueError` on invalid values.
- Verification: Added a config test covering invalid values for all three enum env vars; full gates are run after this note.
- Impact: Catches deployment typos before startup instead of running the collector in an unintended mode.

## 2026-05-25 - Enabled source config fails fast

- Reason: enabled HN/review sources with empty or malformed source configuration could silently run as successful zero-item jobs, and invalid Reddit feed names could fall back to unintended default feeds.
- Change: Validate source JSON arrays during config import, require non-empty HN keywords when `HN_ENABLED=1`, require at least one enabled review target with `site`, `name`, and `url` when `REVIEWS_ENABLED=1`, and reject unsupported Reddit feed names.
- Verification: Added config tests for invalid enabled-source env and valid enabled-source env; full gates are run after this note.
- Impact: Prevents source misconfiguration from looking like normal no-data collection in deployed scheduler runs.

## 2026-05-25 - Scheduler env ranges fail fast

- Reason: invalid digest/macro hours, minutes, weekdays, or source intervals were only rejected later by scheduler job construction or silently clamped, making deployment errors harder to diagnose.
- Change: Validate scheduler-facing env ranges and weekday values during config import.
- Verification: Added config tests for invalid digest, macro, HN interval, and review interval values; full gates are run after this note.
- Impact: Catches broken schedule configuration before runtime job loading and keeps operator errors explicit.

## 2026-05-25 - Export and digest filenames include microseconds

- Reason: CSV exports and daily digest documents used second-resolution timestamps, so repeated operator actions or scheduler retries within the same second could overwrite report artifacts.
- Change: Include microseconds in export CSV and daily digest `.docx` filenames.
- Verification: Added filename pattern assertions covering microsecond-resolution export and digest artifacts; full gates are run after this note.
- Impact: Preserves distinct report artifacts during rapid repeated runs and makes operator/debug evidence less ambiguous.

## 2026-05-25 - Report artifact scopes are filename-safe

- Reason: report and CSV artifact filenames included run labels/scopes directly, so an untrusted or corrupted scheduler/source scope containing path separators could escape `REPORTS_DIR`.
- Change: Sanitize pipeline report run labels and export scopes into safe filename stems before writing local artifacts.
- Verification: Added targeted pipeline and export tests proving path-like scopes stay under the configured reports directory; full gates are run after this note.
- Impact: Hardens local report storage against path traversal and keeps artifact names predictable for operators.

## 2026-05-25 - Telegram card callbacks avoid long post IDs

- Reason: Telegram callback payloads are limited to 64 bytes, but card action buttons embedded raw `post_id` values; long review-source IDs could make notifications fail to send.
- Change: Use existing session token plus item index for triage, deep-dive, and GTM card callbacks while preserving legacy callback parsing.
- Verification: Added bot tests proving long-ID card callbacks stay under the Telegram limit and resolve back to the original post ID; full gates are run after this note.
- Impact: Keeps review-source and other long-ID pain cards actionable in Telegram without losing callback compatibility.

## 2026-05-25 - Telegram replies cap external and LLM text

- Reason: Telegram message text has a hard length limit, while card fields, deep-dive summaries, digest rows, macro summaries, and GTM copy can include unbounded external or LLM-generated text.
- Change: Add a shared Telegram text limiter and apply it to pain cards plus generated deep-dive, digest, macro, and GTM replies.
- Verification: Added bot tests proving long card fields, deep-dive summaries, and GTM output stay within the Telegram text limit; full gates are run after this note.
- Impact: Prevents oversized operator responses from failing at send/edit time while preserving a visible truncation marker.
