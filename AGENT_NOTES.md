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

## 2026-05-25 - Scheduled collection no longer depends on Telegram delivery

- Reason: Scheduled analysis and external-source jobs sent Telegram notifications after successful collection; a transient Telegram failure could make the scheduler treat the whole job as failed and skip normal success bookkeeping.
- Change: Wrap grouped notifications and direct Telegram alert messages in safe helpers that log delivery failures, cap message text, and do not raise back into collection jobs.
- Verification: Added main tests proving grouped notification and direct-message failures are swallowed after attempting delivery; full gates are run after this note.
- Impact: Keeps Reddit/HN/review collection and budget-pause state transitions reliable even when Telegram delivery is temporarily unavailable.

## 2026-05-25 - Runtime numeric config fails fast

- Reason: Several critical numeric env vars were parsed with raw `int()`/`float()` and accepted invalid runtime values such as zero token limits, impossible similarity thresholds, or non-positive source limits until later runtime failures.
- Change: Reuse strict config helpers for LLM token limits, classifier concurrency, scraper retry/comment settings, WTP thresholds, digest windows, budget, clustering thresholds, and source collection limits.
- Verification: Added config tests covering invalid runtime numeric values; full gates are run after this note.
- Impact: Converts bad deploy configuration into clear startup errors instead of late OpenAI/OpenRouter, scheduler, clusterer, or source-collection failures.

## 2026-05-25 - Source smoke checks reject bad source env

- Reason: `smoke_collect.py` intentionally avoids the full app config so it can run without Telegram/LLM credentials, but it silently defaulted invalid source-related env values that the app would reject or mishandle later.
- Change: Make smoke source env parsing strict for JSON arrays, Reddit feed names, source numeric limits, retry settings, HN lookback, and review limits; report config errors as structured smoke failures.
- Verification: Added smoke tests proving invalid source JSON and numeric env values return a failing payload before any source fetch; full gates are run after this note.
- Impact: Makes the pre-deploy collection smoke check a trustworthy gate instead of masking broken source configuration.

## 2026-05-25 - CSV exports are written atomically

- Reason: `/export` CSV artifacts were written directly to their final path, so a process interruption or write/replace failure could leave a partial `.csv` in `REPORTS_DIR`.
- Change: Write export CSVs to a `.tmp` file, replace atomically with `os.replace`, and clean temporary files on failure.
- Verification: Added an export test proving an atomic replace failure removes the temporary file and leaves no final CSV; full gates are run after this note.
- Impact: Keeps operator export artifacts consistent with the project-wide atomic report-write contract.

## 2026-05-25 - Provider env values are validated

- Reason: Unknown `LLM_PROVIDER`, `EMBED_PROVIDER`, or `DSPY_PROVIDER` values could silently fall through to generic OpenAI-compatible defaults, causing requests to hit the wrong endpoint or use the wrong token semantics.
- Change: Add explicit provider allowlists and make `openai-codex` default embedding/DSPy providers to `codex`, since the ChatGPT Codex backend is not an embeddings or DSPy provider.
- Verification: Added config tests for invalid provider values and `openai-codex` defaults; full gates are run after this note.
- Impact: Turns provider typos into startup errors and avoids accidental routing of embedding/DSPy traffic to unsupported backends.

## 2026-05-25 - Operator status replies are capped

- Reason: `/list`, `/status`, and `/budget` could build unbounded Telegram messages from monitored subreddit rows or runtime pause reasons, causing diagnostic commands to fail when operators most need them.
- Change: Apply the shared Telegram text limiter to remaining multi-line operator status replies.
- Verification: Added bot tests proving large monitoring output and long pause reasons stay within the Telegram text limit; full gates are run after this note.
- Impact: Keeps core operational diagnostics usable under large deployments and unusual runtime state.

## 2026-05-25 - Provider API bases accept endpoint URLs

- Reason: `LLM_API_BASE` and `EMBED_API_BASE` were treated only as root API URLs, so operators pasting full `/chat/completions`, `/responses`, or `/embeddings` endpoints produced invalid doubled request URLs.
- Change: Normalize LLM and embedding API base URLs to accept either root API bases or full endpoint URLs without duplicating suffixes.
- Verification: Added OpenRouter and embedder URL normalization tests; full gates are run after this note.
- Impact: Makes provider/gateway deployments less fragile and prevents late request failures caused by common endpoint-style env values.

## 2026-05-25 - Review target URLs fail fast

- Reason: enabled `REVIEW_TARGETS_JSON` entries only required a non-empty `url`, so malformed values such as `u1` or unsupported schemes reached the review fetcher and failed late during source collection.
- Change: Validate enabled review targets as absolute `http` or `https` URLs in the main app config and the source smoke config.
- Verification: Added config and smoke tests for invalid review target URLs; full gates are run after this note.
- Impact: Turns review-source deployment mistakes into clear startup/smoke failures before scheduled collection runs.

## 2026-05-25 - Model pricing config is strict

- Reason: invalid `LLM_MODEL_PRICING_JSON` silently fell back to `{}`, which could make token usage record zero cost and weaken daily budget pause semantics.
- Change: Parse model pricing as a required JSON object shape when provided, normalize numeric price fields to floats, and reject malformed, non-numeric, or negative values at startup.
- Verification: Added config tests for malformed pricing JSON and valid numeric normalization; full gates are run after this note.
- Impact: Keeps cost accounting and budget guardrails from being disabled by a typo in pricing configuration.

## 2026-05-25 - Review scraping blocks private URLs

- Reason: review targets are operator-configured fetch URLs, and the scraper path itself could fetch localhost or private IP literals if called outside the main config validation path.
- Change: Add a shared public HTTP URL validator and enforce it in app config, source smoke config, and `ReviewScraper._fetch_html`.
- Verification: Added config, smoke, and scraper tests for malformed and private review target URLs; full gates are run after this note.
- Impact: Reduces SSRF-style exposure from review ingestion while preserving public `http` and `https` review pages.

## 2026-05-25 - Quality gates include URL safety helper

- Reason: `url_safety.py` became a shared security helper, but CI and documented mypy commands did not include it, leaving the new guard outside the explicit typecheck surface.
- Change: Add `url_safety.py` to the GitHub Actions, README, and AGENTS mypy commands; also update AGENTS required-key wording to the current LLM env aliases.
- Verification: Full gates are run after this note.
- Impact: Keeps local agent guidance, docs, and CI aligned with the deploy-critical security helper.

## 2026-05-25 - Required credentials ignore blank env values

- Reason: required credential lookup treated an explicitly blank `LLM_API_KEY` as present and ignored valid legacy aliases, causing late provider failures with an empty bearer token.
- Change: Make env alias lookup skip blank values and require non-empty Telegram token/chat id values at config import time.
- Verification: Added config tests for blank primary LLM key fallback and blank required credential rejection; full gates are run after this note.
- Impact: Converts common deployment secret wiring mistakes into clear startup failures instead of broken runtime API calls.

## 2026-05-25 - Reddit scraper validates subreddit names

- Reason: bot commands normalize subreddit names, but direct scraper and smoke paths could accept malformed names and build invalid Reddit URLs before failing late in network fallbacks.
- Change: Validate subreddit names inside `RedditScraper.fetch_posts` and `fetch_full_thread`, matching the public command contract.
- Verification: Added scraper tests for malformed subreddit rejection before network calls; full gates are run after this note.
- Impact: Keeps source collection failures explicit and prevents malformed operator inputs from triggering unnecessary external requests.

## 2026-05-25 - HN malformed payloads fail per query

- Reason: Hacker News ingestion only handled HTTP failures per keyword; a 200 response with malformed or non-object JSON could crash the whole source job even when later keywords would succeed.
- Change: Treat malformed HN response payloads as per-keyword failures, keep the all-keywords-failed error, and tolerate invalid score values as zero.
- Verification: Added HN scraper tests for malformed per-keyword payloads and all-malformed failure; full gates are run after this note.
- Impact: Makes HN collection resilient to transient bad upstream responses without hiding complete source failure.

## 2026-05-25 - Source validation docs match runtime

- Reason: README listed review and smoke env names but did not document the runtime contract added for public review URLs and subreddit validation.
- Change: Document that enabled review targets require public `http`/`https` URLs and that smoke checks validate subreddit/review target inputs before network calls.
- Verification: Full gates are run after this note.
- Impact: Keeps deployment docs aligned with the source-ingestion safety checks operators will hit.

## 2026-05-25 - HN hit fields are type-tolerant

- Reason: HN ingestion still assumed individual hit fields were strings; a valid JSON response with numeric/null title, body, or URL fields could crash the whole source job.
- Change: Normalize HN text fields through a safe converter and fall back to the canonical HN item URL when URL fields are missing or non-text.
- Verification: Added an HN scraper test for non-string hit fields; full gates are run after this note.
- Impact: Improves HN collection resilience against partial upstream schema drift without accepting empty unusable hits.

## 2026-05-25 - Review rating parsing is type-tolerant

- Reason: review-source HTML and JSON-LD are external inputs; malformed `reviewRating` shapes or non-numeric rating values could crash a whole review target.
- Change: Add safe rating coercion for JSON-LD parsing and final review filtering, so bad rows are skipped while valid negative reviews still collect.
- Verification: Added review scraper tests for bad JSON-LD rating shapes and bad parsed rating rows; full gates are run after this note.
- Impact: Makes review-source collection more robust against third-party markup drift.

## 2026-05-25 - Google worksheet names are sanitized

- Reason: CSV export scopes were filename-safe, but Google Sheets worksheet names still used raw prefix/subreddit values that can contain invalid title characters or exceed Sheets title limits.
- Change: Build worksheet names from sanitized prefix/scope stems and cap them to the Google Sheets title length limit.
- Verification: Added export tests for worksheet name sanitization and Sheets upsert title usage; full gates are run after this note.
- Impact: Keeps optional Sheets export from failing on unusual but accepted export scopes or operator-provided worksheet prefixes.

## 2026-05-25 - Monitor failures are visible

- Reason: scheduled subreddit failures only logged exceptions; `/list` still showed the previous successful check or `never`, hiding the most recent failed attempt from operators.
- Change: Add `last_attempted_at` and `last_error` to monitored subreddit state, record failures in the scheduler, clear errors on success, and surface the last error in `/list`.
- Verification: Added DB migration/state tests, scheduler failure tests, and bot list rendering tests; full gates are run after this note.
- Impact: Improves recurring collection observability without marking failed jobs as successful.

## 2026-05-25 - Monitor state docs match runtime

- Reason: monitored subreddit state now records last attempts and errors, but README data model highlights did not mention this operator-visible table.
- Change: Document `monitored_subreddits` last success/attempt/error fields in the data model overview.
- Verification: Full gates are run after this note.
- Impact: Keeps deploy/runbook docs aligned with scheduler failure observability.

## 2026-05-25 - Review target disabled flags match config semantics

- Reason: `config.py` and smoke checks treat string disabled values such as `"false"` and `"off"` as disabled, but `main._build_review_targets()` converted non-empty strings to `True`.
- Change: Parse review target enabled values in `main.py` with the same false-value set used by config and smoke paths.
- Verification: Added a regression test for string disabled review target flags; full gates are run after this note.
- Impact: Prevents explicitly disabled review targets from being fetched during scheduled review ingestion.

## 2026-05-25 - Boolean and chat id env values fail clearly

- Reason: deploy-critical boolean env typos such as `HN_ENABLED=flase` were treated as enabled, and non-integer `TELEGRAM_CHAT_ID` values failed with a raw cast error.
- Change: Make boolean env parsing strict for known true/false tokens and validate `TELEGRAM_CHAT_ID` with a clear integer error.
- Verification: Added config regression tests for invalid boolean tokens and non-integer chat ids; full gates are run after this note.
- Impact: Turns common `.env` mistakes into explicit startup failures instead of accidental scheduled jobs or confusing first-run errors.

## 2026-05-25 - Docker healthcheck is read-only against SQLite

- Reason: the container healthcheck called `Database.init()`, so a periodic liveness probe could run DDL, migrations, index creation, and seed writes against the live database.
- Change: Open the configured SQLite database in read-only mode for health checks, verify required tables exist, and read runtime/monitoring summary without initializing schema.
- Verification: Added healthcheck tests for initialized DB success, missing DB failure, and uninitialized DB staying untouched; full gates are run after this note.
- Impact: Keeps startup migrations owned by the application path and prevents health probes from mutating production SQLite state.

## 2026-05-25 - DSPy parser checks budget before LLM calls

- Reason: the optional DSPy parser can make LLM calls outside `OpenRouterClient`; the pipeline checked budget only once before a batch, so long DSPy batches did not enforce pause semantics per request.
- Change: Inject the existing `BudgetGuard` into `DSPyRedditPainParser` and call `ensure_can_spend()` before each DSPy analysis call.
- Verification: Added DSPy parser tests for per-call budget checks and pause propagation, plus a main wiring assertion; full gates are run after this note.
- Impact: Keeps the optional DSPy LLM path aligned with project budget-pause guardrails.

## 2026-05-25 - CI validates Docker Compose config

- Reason: Docker Compose config validation is part of the local deploy gate, but CI and README quality gates did not include it.
- Change: Add `docker compose config -q` to GitHub Actions and the README quality gate command list.
- Verification: Full gates are run after this note.
- Impact: Catches broken container wiring before merge instead of only during local/deploy checks.

## 2026-05-25 - Review target enabled flags are strict

- Reason: global boolean env values were strict, but `REVIEW_TARGETS_JSON[*].enabled` still treated typos such as `"flase"` as enabled and could fetch targets operators intended to disable.
- Change: Parse review target `enabled` values with the same true/false token set in app config, smoke config, and main target construction.
- Verification: Added config, smoke, and main regression tests for invalid per-target enabled flags; full gates are run after this note.
- Impact: Prevents typo-enabled external review collection during deploy and smoke checks.
