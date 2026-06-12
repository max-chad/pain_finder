# AGENT_NOTES

## 2026-06-12 - Normalize provider embeddings for cosine dedup

- Reason: the deduplicator treats embedding dot products as cosine similarity, but remote and sentence-transformers vectors were accepted without L2 normalization, so large-magnitude provider vectors could inflate similarity and trigger false cross-source merges.
- Change: Normalize validated provider and sentence-transformers embeddings to unit length; zero vectors now fail validation and use the existing fallback path.
- Verification: Added a regression where provider embedding `[3.0, 4.0]` is returned as `[0.6, 0.8]` before dedup sees it.
- Impact: Keeps cross-source dedup thresholds meaningful across embedding providers and reduces false merge/data-loss risk.

## 2026-06-12 - Reject malformed embedding vectors before dedup

- Reason: `Embedder.embed()` promised `list[float]` but returned malformed provider payloads such as `["not-a-number"]` unchanged, which could crash cosine similarity or persist unusable vectors in dedup state.
- Change: Validate remote and sentence-transformers embeddings as non-empty finite numeric lists; malformed vectors now trigger the existing fallback chain and ultimately the deterministic bag-of-words embedding.
- Verification: Added a regression where a provider returns a non-numeric embedding and `embed()` falls back to the local BOW vector.
- Impact: Keeps cross-source dedup and embedding backfill reliable under malformed provider responses.

## 2026-06-12 - Preserve manual value when merging existing duplicates

- Reason: `Database.merge_duplicate()` marked an existing duplicate row as `merged` without transferring a manual `favorite` triage or completed deep-dive summary to the canonical row, so dedup backfill could hide operator-selected value from exports and digests.
- Change: When the duplicate row exists, promote the canonical row to `favorite` and copy a completed deep-dive status/summary if the canonical row has not already completed one; keep the no-duplicate-row pipeline merge path unchanged.
- Verification: Added a regression where a favorite duplicate with a completed deep dive is merged and the canonical row preserves both signals.
- Impact: Prevents cross-source dedup/backfill from silently dropping high-value manual triage and enrichment state.

## 2026-06-12 - Document review target requirement for all-source smoke

- Reason: README listed `python smoke_collect.py --source all --limit 5` as a generic source smoke command, but the implementation intentionally fails closed when no enabled `REVIEW_TARGETS_JSON` entries exist.
- Change: Keep the safe Reddit and HN smoke commands as first-run examples and document that `--source all` should be used only after configuring review targets.
- Verification: Added a README regression that rejects the unqualified all-source command and requires the review-target warning.
- Impact: Prevents operators from treating an expected reviews configuration failure as a broken Reddit/HN readiness check during deployment.

## 2026-06-12 - Record OpenRouter usage before payload shape parsing

- Reason: the OpenRouter chat-completions path accessed `choices[0]` before recording provider `usage`, so malformed but billable responses could return `None` without updating the local LLM spend ledger.
- Change: Record response usage immediately after the provider response is received, before parsing `choices` or validating/cache-checking the payload.
- Verification: Added a regression where a response with `usage` but an empty `choices` array returns `None` and still calls `BudgetGuard.record_usage()`.
- Impact: Keeps budget/cost accounting accurate when paid provider calls produce unusable payload shapes.

## 2026-06-12 - Codex empty responses still record usage

- Reason: the OpenAI Codex Responses path returned `(None, usage)` for empty model output, but `_request_json_response()` exited before recording usage, so failed/empty provider calls could bypass the LLM spend ledger.
- Change: Record Codex Responses usage immediately after the provider call, before returning on `payload is None` or validating/cache-checking the payload.
- Verification: Added an OpenRouter regression where an empty Codex response with usage returns `None` but still calls `BudgetGuard.record_usage()`.
- Impact: Keeps budget accounting accurate for spend-producing Codex calls even when the model returns unusable output.

## 2026-06-12 - OAuth comment enrichment falls back to RSS

- Reason: authenticated Reddit collection used OAuth for top-comment hydration, but an OAuth comment failure or empty/malformed listing returned no comments instead of using the existing old.reddit RSS fallback, weakening downstream consensus/workaround scoring.
- Change: Route OAuth top-comment failures and empty comment listings through `_fetch_comments_rss()`, matching the public JSON enrichment path.
- Verification: Added scraper regressions for OAuth comment failure and empty OAuth listing falling back to RSS.
- Impact: Improves authenticated Reddit collection quality and keeps comment-market signals available when the OAuth comments endpoint degrades.

## 2026-06-12 - Optional DSPy install path fails closed on known CVE

- Reason: `python -m pip_audit -r requirements-dspy.txt` still reports `diskcache 5.6.3` / `CVE-2025-69872` through optional DSPy, with no fixed version reported, so the documented optional install path remained known-vulnerable.
- Change: Remove `dspy>=3.2` from the project-managed optional requirements file, leave the file as an audited fail-closed placeholder, and update README guidance to keep DSPy disabled until it can be re-added with a clean audit.
- Verification: Added a README/requirements regression asserting the fail-closed status and rerun optional dependency audit after the change.
- Impact: Prevents operators from installing a known-vulnerable optional parser path via repository-provided commands while preserving the lazy runtime seam for a future audited DSPy install.

## 2026-06-12 - Roll back pain point writes on secondary index failures

- Reason: `Database.insert_pain_point()` could fail after the main `pain_points` upsert but before competitor index replacement, then leave the uncommitted row visible on the connection and eligible to be committed by a later successful operation.
- Change: Roll back the SQLite transaction in the insert error path before re-raising.
- Verification: Added a regression that forces `_replace_competitor_tags()` to fail and proves the partially inserted pain point is absent after the exception.
- Impact: Prevents partial pain-point persistence when secondary writes fail, preserving DB consistency across ingestion errors.

## 2026-06-12 - Budget pause only gates real LLM classification work

- Reason: `AnalysisPipeline._analyze_posts()` checked budget/pause state before filtering already-seen posts or empty batches, so a run with no fresh LLM candidates could be blocked as if it would spend tokens.
- Change: Move the budget/pause check to immediately before `classify_batch()` and skip classification entirely when no fresh candidates remain after existing-row filtering and prescreening.
- Verification: Added pipeline regressions for empty and existing-only paused batches, while preserving pause enforcement for fresh candidates.
- Impact: Keeps budget caps focused on spend-producing LLM work and preserves cheap ingestion diagnostics/reporting for duplicate or empty source runs.

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

## 2026-05-25 - Live eval uses runtime budget guard

- Reason: `eval/run_eval.py --live` builds LLM clients outside the production composition root and did not attach `BudgetGuard`, so eval runs could ignore pause state and usage ledger semantics.
- Change: Initialize the configured database for live eval, create a `BudgetGuard`, pass it to OpenRouter and optional DSPy clients, and close the DB after prediction generation.
- Verification: Added eval-runner tests for budget guard wiring and DB cleanup; full gates are run after this note.
- Impact: Keeps quality-eval LLM spending under the same runtime budget controls as data collection.

## 2026-05-25 - Healthcheck test closes raw SQLite probe

- Reason: the healthcheck regression test used `sqlite3.Connection` as a context manager, which commits/rolls back but does not close the connection and caused intermittent `ResourceWarning` noise in full test runs.
- Change: Explicitly close the raw SQLite connection after reading table names.
- Verification: Warning-focused pytest and full gates are run after this note.
- Impact: Keeps CI warning output focused on real lifecycle regressions.

## 2026-05-25 - URL safety rejects numeric IP bypass forms

- Reason: review target URL validation rejected standard private IP literals, but legacy numeric IPv4 forms such as `2130706433` or octal dotted hosts could bypass `ip_address()` parsing.
- Change: Reject ambiguous all-numeric and hex/octal-like hostnames that are not accepted as standard public IP literals.
- Verification: Added URL safety tests for public hosts, private hosts, credentials, unsupported schemes, and numeric localhost bypass forms; full gates are run after this note.
- Impact: Reduces SSRF-style exposure from operator-configured review targets.

## 2026-05-25 - LLM usage token counts are tolerant

- Reason: provider `usage` payloads are external inputs; malformed or negative token counts could raise during usage accounting after a valid model response and discard the result.
- Change: Coerce usage token counts through a non-negative safe parser for OpenRouter chat responses and OpenAI/Codex response usage objects.
- Verification: Added OpenRouter usage tests for malformed and negative token counts; full gates are run after this note.
- Impact: Keeps successful LLM classifications from failing because optional usage metadata drifted.

## 2026-06-01 - Export warnings fit Telegram replies

- Reason: `/export` limited the CSV document itself, but auxiliary Google Sheets URL and warning replies could exceed Telegram text limits when upstream errors were verbose.
- Change: Apply the shared Telegram text limiter to export sheet URL and warning replies.
- Verification: Added a bot regression test for long export warnings; full gates are run after this note.
- Impact: Keeps operator export diagnostics deliverable even when optional Sheets export fails noisily.

## 2026-06-01 - HN smoke rejects empty keyword config

- Reason: source smoke checks parsed `HN_KEYWORDS_JSON=[]` as an empty list and then fell back to built-in default keywords, masking an explicit broken source configuration.
- Change: Treat an explicitly provided empty HN keyword list as a smoke config error before any network fetch.
- Verification: Added a smoke regression test for empty HN keyword env; full gates are run after this note.
- Impact: Keeps pre-deploy HN smoke aligned with app startup validation and prevents false-positive collection readiness.

## 2026-06-01 - Source smoke rejects zero limits

- Reason: source smoke CLI accepted `--limit 0` and silently normalized it to `1`, so a broken operator preflight command could pass with parameters different from the requested run.
- Change: Return a structured config error for non-positive smoke limits while preserving the existing upper safety cap.
- Verification: Added a smoke regression test for `--limit 0`; full gates are run after this note.
- Impact: Makes deploy/source-readiness checks fail clearly on invalid operator input instead of masking it.

## 2026-06-01 - Telegram operator replies are bounded

- Reason: manual `/deepdive` and `/gtm` commands accepted valid but arbitrarily long post IDs, and grouped list views could grow past Telegram's text limit after repeated `Load more`.
- Change: Apply the existing Telegram text limiter to user-controlled post-id replies and list-view rendering while keeping post-id parsing and keyboard callbacks compatible with existing source-prefixed IDs.
- Verification: Added bot regression tests for long post IDs in deep-dive not-found and GTM progress replies, plus a many-item list rendering limit test; full gates are run after this note.
- Impact: Prevents authorized operator input or large grouped notifications from breaking Telegram reply/edit delivery before the expensive action or diagnostic response can complete.

## 2026-06-01 - Reviews smoke requires enabled targets

- Reason: `smoke_collect.py --source reviews` returned success with zero configured review targets, so a deploy/source-readiness check could pass without exercising reviews ingestion.
- Change: Treat an explicitly requested reviews smoke, including `--source all`, as a config error when no enabled review targets exist.
- Verification: Added smoke regression tests for explicit reviews and all-source runs with no enabled review targets; full gates are run after this note.
- Impact: Prevents false-positive reviews readiness before data collection.

## 2026-06-01 - Competitor lookups exclude inactive rows

- Reason: competitor pain lookup helpers still counted `discarded` and `merged` pain points, unlike export, digest, and recent-pain queries.
- Change: Filter competitor drilldown and top-tag queries to active canonical rows only.
- Verification: Added a DB regression test for discarded and merged competitor-tag rows; full gates are run after this note.
- Impact: Keeps competitor analysis from being inflated by rejected or deduplicated records.

## 2026-06-01 - OpenRouter provider failures are contained

- Reason: malformed provider response shapes could escape as `TypeError`/`AttributeError`, and usage-ledger write failures after a successful paid response could discard the valid result.
- Change: Treat malformed provider payload shapes as request failures returning `None`, and log usage-recording failures without raising after a valid provider result.
- Verification: Added OpenRouter regression tests for malformed payload shapes and ledger-write failures on both chat-completion and usage-dict accounting paths; full gates are run after this note.
- Impact: Keeps external provider drift and transient accounting writes from crashing classification or wasting paid results.

## 2026-06-01 - DSPy parser spend is accounted

- Reason: optional DSPy classification checked budget before provider calls but did not record usage afterward, so DSPy spend could bypass the daily cap ledger.
- Change: Pass runtime pricing into the DSPy parser, record DSPy usage from LM history when available, fall back to a token estimate when priced, and skip DSPy when budget enforcement is active but pricing is missing.
- Verification: Added DSPy parser regression tests for usage recording, exact LM-history usage, and fail-closed missing-pricing behavior; full gates are run after this note.
- Impact: Keeps the optional DSPy path aligned with the same budget-cap semantics as the primary OpenRouter client.

## 2026-06-01 - Reddit score parsing is tolerant

- Reason: malformed Reddit JSON `score` values could raise inside `_build_post()` and push a whole fetch path into fallback instead of preserving otherwise valid posts.
- Change: Coerce invalid Reddit score values to `0`, matching the defensive behavior already used for Hacker News payloads.
- Verification: Added a scraper regression test for malformed Reddit score values; full gates are run after this note.
- Impact: Keeps ingestion resilient to external source field drift without dropping usable source posts.

## 2026-06-01 - Quality gates include runtime parser modules

- Reason: CI, README, and agent command docs omitted `dspy_parser.py`, `eval/run_eval.py`, and `eval_harness.py` from the mypy gate even though these modules are part of runtime parsing, evaluation, and budget-sensitive LLM wiring.
- Change: Align the documented and CI mypy command with the full local gate used during audit.
- Verification: Targeted mypy and full gates are run after this note.
- Impact: Prevents future parser/eval type regressions from passing CI while failing the local deploy gate.

## 2026-06-01 - Review HTML fetches are bounded

- Reason: configured review pages are external inputs, and the scraper previously read `response.text` without an application-level byte limit, allowing a misconfigured or hostile target to consume unbounded memory during collection.
- Change: Stream review HTML responses and abort collection when the response exceeds the scraper's configured byte limit.
- Verification: Added scraper review tests for normal bounded HTML fetches and oversized responses; full gates are run after this note.
- Impact: Reduces deploy-time DoS risk from review-source collection while preserving existing parsing behavior for normal pages.

## 2026-06-01 - Reddit comment payloads are shape-tolerant

- Reason: Reddit comment payloads are external JSON inputs, and top-comment/full-thread parsing assumed the listing and child nodes were dictionaries, so malformed payload shapes could crash comment hydration or deep-dive collection.
- Change: Add a shared listing-child extractor and skip malformed comment nodes while preserving valid sibling and nested comments.
- Verification: Added scraper tests for malformed comment listings and malformed nested comment nodes; full gates are run after this note.
- Impact: Keeps Reddit collection resilient to upstream schema drift and partial malformed responses.

## 2026-06-01 - Reddit RSS fallback skips malformed XML peers

- Reason: RSS fallback fetches multiple Reddit feeds/searches, but XML parsing happened outside per-feed error handling, so one malformed old.reddit response could abort otherwise usable RSS collection.
- Change: Catch RSS parse failures per feed/search payload and continue merging valid peer results.
- Verification: Added scraper tests for malformed feed XML alongside a valid feed and malformed search XML alongside valid feed results; full gates are run after this note.
- Impact: Improves data-collection reliability when Reddit returns a block page or partial malformed RSS payload for one request.

## 2026-06-01 - Review URLs require public DNS resolution

- Reason: review targets are operator-configured external URLs; syntactic private-host checks rejected literals but still allowed domains that resolve to private, loopback, link-local, reserved, or unspecified addresses at fetch time.
- Change: Add an async resolved-URL safety check and require review target hostnames to resolve only to public addresses immediately before fetching.
- Verification: Added URL safety tests for public/private DNS results and scraper tests for resolved-private review targets; full gates are run after this note.
- Impact: Reduces SSRF risk from review collection without adding DNS lookups to import-time configuration parsing.

## 2026-06-01 - Review smoke honors source limit

- Reason: `smoke_collect --limit` is documented as a per-source limit, but review smoke passed it as a per-target limit, so multiple configured review targets could trigger more external collection work than the deploy gate requested.
- Change: Add an optional total cap to review target collection and pass the CLI limit as the reviews source total during smoke checks.
- Verification: Added review scraper tests for total-limit allocation and smoke tests asserting the reviews source limit is forwarded as `max_total`; full gates are run after this note.
- Impact: Keeps deploy smoke checks bounded and predictable when multiple review targets are configured.

## 2026-06-01 - URL safety rejects encoded hostnames

- Reason: percent-encoded hostnames can obscure private or link-local targets from syntactic checks while being normalized differently by downstream HTTP clients or proxies.
- Change: Reject hostnames containing `%` before public-host or DNS checks.
- Verification: Added URL safety tests for percent-encoded localhost-style hostnames and scoped IPv6 link-local hosts; full gates are run after this note.
- Impact: Reduces SSRF bypass risk for operator-configured review target URLs.

## 2026-06-01 - Scheduled job failures are persisted

- Reason: subreddit monitor failures were persisted in `monitored_subreddits`, but macro, Hacker News, review, and digest scheduled jobs only logged failures, leaving operators blind after log rotation or restart.
- Change: Add `scheduled_job_status`, record success/failure for non-subreddit scheduled jobs, and surface active scheduled-job errors in `/status`.
- Verification: Added DB, scheduler, and bot status tests for scheduled-job failure persistence and clearing; full gates are run after this note.
- Impact: Improves deploy observability for source collection and digest jobs without changing collector behavior.

## 2026-06-01 - Healthcheck reports scheduled job errors

- Reason: after persisting scheduled-job failures, the container healthcheck still returned only storage and monitoring counts, so deploy diagnostics could miss a source/digest job failure without opening Telegram.
- Change: Include a read-only `scheduled_job_errors` count in healthcheck output while keeping liveness success independent from historical job failures.
- Verification: Updated healthcheck tests to seed a scheduled job failure and assert the reported error count; full gates are run after this note.
- Impact: Makes container-level diagnostics more informative without causing restart loops for recoverable upstream source outages.

## 2026-06-01 - README documents scheduler diagnostics and review DNS safety

- Reason: README still described healthcheck and review smoke safety at the older level, omitting `scheduled_job_errors` and fetch-time public DNS resolution.
- Change: Document the healthcheck diagnostic counter and the public-address resolution requirement for review targets.
- Verification: Documentation-only change; full gates are run after this note to keep the checkpoint consistent.
- Impact: Keeps deploy/runbook expectations aligned with the current hardening behavior.

## 2026-06-01 - Reddit and HN response bodies are bounded

- Reason: Reddit JSON/RSS and Hacker News JSON collectors read external response bodies without an application-level byte cap, allowing oversized responses to consume unbounded memory before parsing.
- Change: Stream Reddit JSON/RSS and HN JSON responses through collector-level byte limits before decoding/parsing.
- Verification: Added scraper tests for oversized Reddit JSON, oversized Reddit RSS, and oversized HN payload handling; full gates are run after this note.
- Impact: Reduces data-collection DoS risk from external sources while keeping existing retry/fallback behavior.

## 2026-06-01 - Collector byte caps are configurable

- Reason: response-size caps were fixed code defaults, leaving deploy operators unable to tune collector limits for constrained containers or known large source responses.
- Change: Add strict env-configured byte caps for Reddit, HN, and review collectors, wire them through main and smoke collection, and document the settings.
- Verification: Added config/main/smoke coverage for response-byte env wiring; full gates are run after this note.
- Impact: Makes source collection limits operationally visible and adjustable without code changes.

## 2026-06-01 - Reddit OAuth token responses are bounded

- Reason: Reddit OAuth token acquisition still used an unbounded POST response read, leaving one external Reddit API response outside the collector byte cap.
- Change: Reuse the bounded response reader for OAuth token POST requests before parsing the token JSON.
- Verification: Added a scraper regression test for oversized OAuth token responses; full gates are run after this note.
- Impact: Completes Reddit collector response-size hardening for both content and token endpoints.

## 2026-06-01 - Embedding provider responses are bounded

- Reason: remote embedding calls read provider responses without a byte cap before parsing JSON, even though embedding failures are expected to degrade to local fallbacks.
- Change: Stream embedding provider responses through a byte limit and let oversized responses fall through the existing sentence-transformers/BOW fallback path.
- Verification: Added an embedder regression test proving oversized provider responses fall back to BOW; full gates are run after this note.
- Impact: Reduces runtime memory risk from embedding providers without breaking the embedder's never-raise contract.

## 2026-06-01 - LLM provider responses are bounded

- Reason: OpenRouter/OpenAI-compatible chat responses were parsed with `response.json()` after an unbounded body read, even though malformed provider responses already degrade to `None`.
- Change: Stream chat completion responses through a byte limit before JSON parsing and treat oversized responses as provider failures.
- Verification: Added an OpenRouter regression test for oversized LLM responses returning `None`; full gates are run after this note.
- Impact: Reduces LLM runtime memory risk without changing retry behavior for retryable HTTP/network failures.

## 2026-06-01 - Scheduler diagnostics stay legacy-compatible

- Reason: `scheduled_job_status` is new deploy observability state, so old initialized SQLite databases must keep passing read-only healthchecks and startup must create the new table before scheduler methods use it.
- Change: Add regression coverage for legacy DB healthcheck behavior without `scheduled_job_status` and for `Database.init()` creating usable scheduled-job status storage on an older schema.
- Verification: Added healthcheck and DB migration compatibility tests; full gates are run after this note.
- Impact: Reduces migration risk for existing deployments adopting scheduler diagnostics.

## 2026-06-01 - Codex Responses streams are bounded

- Reason: chat-completions responses were byte-capped, but the OpenAI Responses/Codex backend accumulated streamed output text without enforcing the same LLM response limit.
- Change: Track UTF-8 bytes while reading Responses stream deltas and validate fallback final-response text before JSON parsing.
- Verification: Added an OpenRouter regression test for oversized Codex streamed output returning `None`; full gates are run after this note.
- Impact: Closes the remaining LLM provider response-size gap and keeps Codex backend failures on the existing safe fallback path.

## 2026-06-01 - DSPy primary parser has a timeout

- Reason: the optional DSPy primary parser runs in a worker thread before legacy fallback, but had no explicit timeout, so a stuck provider call could block classification progress.
- Change: Add `DSPY_TIMEOUT_SECONDS`, pass it into `dspy.LM`, and wrap the threaded DSPy call in `asyncio.wait_for`.
- Verification: Added config/main/DSPy parser tests for timeout wiring and timeout fallback; full gates are run after this note.
- Impact: Improves runtime reliability when DSPy is enabled without changing the default disabled state.

## 2026-06-01 - Eval DSPy runtime uses the same timeout

- Reason: the live eval classifier is a second composition root and must not diverge from `main.py` when DSPy is enabled.
- Change: Pass `DSPY_TIMEOUT_SECONDS` into the eval runtime `DSPyRedditPainParser` builder.
- Verification: Extended eval runtime builder tests to assert DSPy timeout wiring; full gates are run after this note.
- Impact: Keeps live evaluation runs under the same bounded-DSPy contract as production runtime.

## 2026-06-01 - Env example lists safety limit knobs

- Reason: `.env.example` omitted deploy-visible byte caps and the new DSPy timeout, so operators copying it would miss important collection/runtime safety controls.
- Change: Add Reddit/HN/review response byte caps and `DSPY_TIMEOUT_SECONDS` to `.env.example`.
- Verification: Added a config test asserting the env example lists these operational limit knobs; full gates are run after this note.
- Impact: Improves deployment DX and makes safety limits discoverable before first run.

## 2026-06-01 - DSPy optional install requires its own audit

- Reason: `python -m pip_audit -r requirements-dspy.txt` still reports `diskcache 5.6.3` / `CVE-2025-69872` through optional DSPy with no fixed version, while the base and ML requirement sets are clean.
- Change: Document that operators should run the optional DSPy audit and keep DSPy disabled in production unless that audit is clean or the residual optional-dependency risk is accepted.
- Verification: Added a README regression test for the optional DSPy audit warning; full gates are run after this note.
- Impact: Prevents the optional parser path from looking production-safe just because the default dependency audit is clean.

## 2026-06-01 - HN posts preserve source timestamps

- Reason: live HN smoke returned posts with `source_created_at=null`, so HN rows flowed into recency scoring and opportunity buckets as `unknown_age` even though Algolia provides creation timestamps.
- Change: Parse `created_at_i` or fallback ISO `created_at` from HN hits into `Post.source_created_at` and `Post.source_created_ts`.
- Verification: Added HN scraper timestamp tests and reran live HN smoke to confirm non-null source timestamps; full gates are run after this note.
- Impact: Restores recency-aware scoring for HN-sourced pain signals.

## 2026-06-01 - Reddit comments have RSS fallback

- Reason: live probes showed unauthenticated `www.reddit.com/comments/*.json` returns 403 while `old.reddit.com/comments/{id}/.rss` works, so RSS-based collection and deep dives could lose all comment context without OAuth credentials.
- Change: Add comments RSS fallback for top-comment hydration and full-thread extraction, skipping the original post entry and parsing comment entries into plain text.
- Verification: Added scraper tests for top-comment and full-thread JSON-blocked fallbacks; full gates are run after this note.
- Impact: Preserves consensus/workaround/comment evidence for default no-OAuth Reddit collection and reduces deep-dive failures.

## 2026-06-12 - Promotion gate fails closed on weak evidence

- Reason: high-scoring founder pitches, news/advice noise, or non-monetizable B2C items could still look like strong opportunities because the pipeline had no explicit promotion eligibility contract.
- Change: Add promotion eligibility and evidence rejection reasons to report/analysis payloads, cap opportunity score for rejected signals, and skip auto deep dives for rejected promotions.
- Verification: Added pipeline tests for noisy founder/news/B2C rejection and grounded first-hand founder acceptance; full gates are run after this note.
- Impact: Reduces false-positive monetization leads in operator output while preserving evidence-backed founder pain.

## 2026-06-12 - Promotion status reaches exports and digest

- Reason: promotion gating stored rejection reasons in analysis payloads, but CSV/Sheets exports and daily digest rendering did not surface those reasons to operators.
- Change: Add promotion columns to exports and render promotion rejection reasons in digest documents.
- Verification: Added export and digest tests for promotion gate visibility; full gates are run after this note.
- Impact: Makes false-positive filtering visible in operator workflows instead of hiding it in raw JSON payloads.

## 2026-06-12 - Export ordering uses opportunity score

- Reason: CSV/Sheets export ordering still prioritized raw willingness-to-pay and pain level, so capped weak-evidence leads could stay above stronger grounded leads.
- Change: Order export rows by manual favorites first, then opportunity score, then legacy WTP/pain tie-breakers; order macro trend candidates by opportunity score before raw WTP/pain.
- Verification: Added DB regression tests where capped WTP=10 noisy leads must sort below grounded high-score leads in export rows and macro candidates.
- Impact: Makes promotion score caps affect the operator's first review surface and macro clustering seed order instead of only report JSON and digest ranking.

## 2026-06-12 - Budget pause keeps daily digest scheduled

- Reason: Scheduler reload returned early when LLM operations were paused, removing daily digest jobs even though digest delivery does not spend LLM budget and is needed for operator visibility during pauses.
- Change: Skip only LLM-spending scheduler jobs (subreddit monitor, macro trend, HN, reviews) while still scheduling daily digest when configured.
- Verification: Added a scheduler regression test that keeps `daily_digest` loaded under `llm_paused=True` while excluding LLM ingest jobs.
- Impact: Preserves reporting/observability during budget pauses instead of making the system go silent.

## 2026-06-12 - RSS fallback retries rate limits

- Reason: Live source smoke showed Reddit public/RSS degradation with `429 Too Many Requests`; JSON requests retried retryable failures, but RSS fallback feed/search/comment requests failed after a single rate-limit response.
- Change: Add a shared response retry wrapper for size-limited GET requests, route RSS feed/search fallback through it with bounded fallback attempts, and keep optional comment RSS fallback on an even shorter retry budget.
- Verification: Added RSS regression tests where old.reddit returns `429` with `Retry-After` before a successful feed response, where fallback feed retries are bounded, and where optional comment RSS retries are bounded.
- Impact: Makes the no-OAuth Reddit fallback more resilient during transient rate limits without turning optional comment hydration into a long-tail collection bottleneck.

## 2026-06-12 - CI type gate covers digest delivery

- Reason: `digest_delivery.py` is a production Hermes/daily-digest path, but the documented and GitHub Actions mypy commands did not include it.
- Change: Add `digest_delivery.py` to the README quality gate and GitHub Actions mypy command.
- Verification: Run the updated mypy command locally after this note.
- Impact: Prevents digest delivery type regressions from passing CI unchecked.

## 2026-06-12 - Healthcheck strict readiness mode

- Reason: Docker liveness intentionally reports scheduled job errors without failing, but deploy/readiness gates need an explicit way to fail when scheduled ingestion or digest jobs have active errors.
- Change: Add `python healthcheck.py --fail-on-job-errors`, which preserves default liveness behavior while raising on active scheduled job errors in strict mode.
- Verification: Added healthcheck tests for strict mode failure and CLI flag wiring.
- Impact: Lets deployment checks catch a degraded collector without making Docker restart a live container for historical job diagnostics.

## 2026-06-12 - Recency knobs documented in env example

- Reason: `CURRENT_OPPORTUNITY_MAX_AGE_DAYS` and `EVERGREEN_MAX_AGE_DAYS` affect freshness scoring and opportunity buckets, but were missing from `.env.example` and the README environment list.
- Change: Add both recency tuning variables to `.env.example` and README, plus a regression test that keeps the example file aligned for those knobs.
- Verification: Added `test_env_example_documents_recency_knobs` and run config/docs checks after this note.
- Impact: Makes deployment freshness/ranking behavior discoverable instead of relying on hidden defaults in `config.py`.

## 2026-06-12 - Resume override survives usage recording

- Reason: `/resume` is intended to override budget pause until the next UTC midnight, but `BudgetGuard.record_usage()` could immediately pause again after the first resumed LLM call when daily spend was already above cap.
- Change: Share active resume-override parsing between pre-spend checks and post-usage pause checks, and skip automatic re-pause while the override is still valid.
- Verification: Added a budget regression test where usage above cap records successfully without re-pausing during an active resume override.
- Impact: Makes operator resume semantics reliable instead of allowing only one resumed request before monitoring pauses again.

## 2026-06-12 - Reject non-finite numeric config values

- Reason: Python accepts `nan` and `inf` as floats, and the existing min/range checks let them through, which could disable or corrupt budget caps, similarity thresholds, temperatures, retry delays, timeouts, and model pricing.
- Change: Require finite float values in shared numeric env parsing and model-pricing normalization.
- Verification: Added config regressions for `nan`/`inf` env values and pricing JSON values; full gates are run after this note.
- Impact: Fails deploy/startup fast on invalid numeric configuration instead of running with non-comparable budget, cost, and threshold values.

## 2026-06-12 - Usage token overflow cannot drop LLM results

- Reason: Provider usage metadata can decode to non-finite numbers such as `inf`; `int(inf)` raised `OverflowError`, so malformed telemetry could drop an otherwise valid LLM or DSPy result.
- Change: Treat overflow token counts as malformed usage and coerce them to zero in the OpenRouter/Codex client and optional DSPy parser.
- Verification: Added regression tests for OpenRouter chat usage, Codex Responses usage conversion, and DSPy usage history parsing with overflow values; full gates are run after this note.
- Impact: Preserves successful classification results and budget-recording attempts when provider telemetry is bad, without inventing spend from untrusted token counts.

## 2026-06-12 - Cap Reddit retry delays from Retry-After

- Reason: A single external `429` response with a huge or non-finite `Retry-After` header could make Reddit collection sleep for days or effectively forever.
- Change: Cap parsed `Retry-After` and exponential fallback delays at `MAX_REDDIT_RETRY_DELAY_SECONDS`.
- Verification: Added a scraper regression for huge and infinite `Retry-After` values while preserving the existing short-delay retry behavior; full gates are run after this note.
- Impact: Keeps scheduled collection responsive under hostile or broken rate-limit headers instead of letting one upstream response stall the collector.

## 2026-06-12 - Legacy report export stays inside reports directory

- Reason: The legacy `/export` fallback opened the latest report path directly from the database, so a corrupted or injected report row could make the bot send an arbitrary local file to Telegram.
- Change: Require fallback report exports to be existing `.json` files under the configured `REPORTS_DIR` before opening them.
- Verification: Added bot regressions for allowed report export inside `REPORTS_DIR` and rejection of an existing JSON file outside that directory; full gates are run after this note.
- Impact: Prevents database path corruption from turning an authorized export command into local file disclosure.

## 2026-06-12 - Review ratings reject non-finite values

- Reason: Review rating payloads such as `"NaN"` parsed to `float("nan")`; comparisons did not reject it, and score calculation crashed on `int(nan)`.
- Change: Treat non-finite review ratings as invalid in the shared rating coercion helper.
- Verification: Added a review-ingest regression proving a NaN rating row is skipped while a valid complaint in the same target is still collected; full gates are run after this note.
- Impact: Keeps review collection resilient to malformed numeric payloads from external review pages.

## 2026-06-12 - URL safety rejects non-global shared address space

- Reason: `100.64.0.0/10` shared address space is not private/reserved in Python's `ipaddress` flags, so review target URLs could pass the public URL guard despite not being globally reachable.
- Change: Require literal and resolved IP addresses to be globally routable and non-multicast.
- Verification: Added URL safety regressions for literal CGNAT addresses and DNS results resolving into CGNAT space; full gates are run after this note.
- Impact: Tightens SSRF protection for operator-configured review targets and blocks another internal/non-public address range.

## 2026-06-12 - LLM usage ledger rejects invalid spend values

- Reason: The database usage ledger accepted negative and non-finite cost values, which could corrupt daily spend totals and budget-pause decisions.
- Change: Validate usage events before insert so token counts are non-negative and `cost_usd` is finite and non-negative.
- Verification: Added DB regressions for negative, NaN, and infinite costs plus negative token counts; full gates are run after this note.
- Impact: Keeps budget accounting monotonic and prevents malformed telemetry from lowering or corrupting spend totals.

## 2026-06-12 - Strict healthcheck includes subreddit monitor failures

- Reason: `healthcheck.py --fail-on-job-errors` counted `scheduled_job_status` failures but ignored active subreddit monitor failures stored on `monitored_subreddits.last_error`.
- Change: Include active monitor rows with `last_error` in the strict job-error count while preserving read-only compatibility with legacy databases that lack the column.
- Verification: Added healthcheck regressions for strict failure on monitor errors and for legacy databases without `scheduled_job_status` or `last_error`; full gates are run after this note.
- Impact: Makes readiness fail when the core subreddit collector is degraded instead of reporting green while ingestion is broken.

## 2026-06-12 - Pain point score fields require finite values

- Reason: The pain-point insert/upsert boundary accepted non-finite score values, so malformed scoring data could persist into ranking, export, digest, and macro-clustering queries.
- Change: Validate all floating score fields in `insert_pain_point()` with a shared finite-number coercion helper before writing to SQLite.
- Verification: Added DB regressions for infinite opportunity score and NaN comment shill risk, plus adjacent insert/upsert checks; full gates are run after this note.
- Impact: Prevents corrupted score values from entering operator-facing prioritization surfaces.

## 2026-06-12 - Source smoke rejects non-finite float env

- Reason: `smoke_collect.py` has an independent env parser and accepted `SCRAPER_RETRY_BASE_DELAY=inf`, allowing the deploy smoke gate to enter network retry paths with an unbounded delay.
- Change: Require finite float env values in the smoke collector before any source fetch starts.
- Verification: Added a smoke regression for non-finite retry delay; full gates are run after this note.
- Impact: Keeps the read-only source smoke gate fast-failing on invalid deploy env instead of hanging during collection probes.

## 2026-06-12 - Macro cluster aggregates reject invalid numbers

- Reason: Macro clustering and canonical cluster persistence trusted numeric aggregates from SQLite rows; legacy/corrupted rows with `inf` could crash `/macro` on timestamp conversion or persist non-finite scores into digest ranking.
- Change: Validate macro run counters, cluster aggregate fields, and member similarities before DB writes; make `MacroTrendClusterer` ignore non-finite legacy candidate values while still using valid members.
- Verification: Added DB regressions for invalid macro aggregate/member values and clusterer regression for legacy rows with infinite WTP, authority, opportunity score, and source timestamp; full gates are run after this note.
- Impact: Keeps the central macro-cluster/digest signal path available and prevents corrupted numeric rows from poisoning canonical cluster ranking.

## 2026-06-12 - Source timestamps tolerate overflow payloads

- Reason: Reddit `created_utc` and Hacker News `created_at_i`/`points` come from external JSON; non-finite or out-of-range numeric values could raise `OverflowError`/platform timestamp errors and abort collection for an otherwise usable response.
- Change: Reject non-finite source timestamps, catch timestamp conversion overflow, and treat overflowing external scores as zero.
- Verification: Added Reddit and HN regressions for infinite external score/timestamp payloads; full gates are run after this note.
- Impact: Keeps source collection resilient to malformed upstream rows instead of dropping an entire subreddit or keyword query.

## 2026-06-12 - OpenAI Codex provider uses Codex defaults

- Reason: `LLM_PROVIDER=openai-codex` was accepted and routed to the Codex Responses backend, but unset `LLM_MODEL` still defaulted to the OpenRouter llama model because default selection did not treat `openai-codex` as Codex-like.
- Change: Include `openai-codex` in the shared Codex/OpenAI-compatible default set for LLM model, temperature, max tokens, and embedding model defaults.
- Verification: Extended config regression coverage for `openai-codex` with `LLM_MODEL`, `LLM_TEMPERATURE`, and `LLM_MAX_TOKENS` unset; full gates are run after this note.
- Impact: Prevents a formally valid Codex-provider deploy from sending incompatible default model names and token settings to the Codex backend.

## 2026-06-12 - Deep-dive callbacks require persisted posts

- Reason: Manual `/deepdive` checked that the post existed before network and LLM work, but legacy inline `deepdive:<post_id>:<subreddit>` callbacks could bypass that check and run a Reddit thread fetch plus deep-dive model call for missing or stale post ids.
- Change: Normalize legacy callback subreddits and require `db.get_pain_point(post_id)` to exist before invoking the injected deep-dive function from callbacks.
- Verification: Added a bot callback regression proving a missing post answers `Post not found` and does not call `deep_dive_fn`; full gates are run after this note.
- Impact: Prevents stale/corrupt inline buttons from triggering avoidable external fetches, LLM spend, and orphaned deep-dive rows.

## 2026-06-12 - Model payload JSON rejects NaN and Infinity

- Reason: Python's default `json.dumps()` writes non-standard `NaN` and `Infinity` tokens, so malformed model payloads could persist invalid JSON into deep-dive rows, the LLM cache, or GTM assets.
- Change: Add a strict JSON serializer for DB payload boundaries and use it for deep-dive payloads, cached LLM payloads, and GTM asset payloads.
- Verification: Added DB regressions for non-finite deep-dive, cached payload, and GTM asset payload values; full gates are run after this note.
- Impact: Keeps persisted model artifacts compatible with standard JSON tooling and prevents corrupted cache/asset rows from becoming operator-facing data debt.

## 2026-06-12 - Monitor intervals stay positive

- Reason: Subreddit monitor intervals were validated by the Telegram parser but not by the DB boundary, and scheduler reload used persisted `interval_hours` directly; a legacy/corrupt zero interval could fail job reload after existing jobs were removed.
- Change: Reject non-positive monitor intervals on `add_monitored_subreddit()` and clamp legacy non-positive persisted intervals to one hour during scheduler reload.
- Verification: Added DB regression for interval `0` rejection and scheduler regression proving a legacy `interval_hours=0` row still schedules a one-hour monitor job; full gates are run after this note.
- Impact: Prevents one bad monitor row from breaking scheduled collection reload and leaving ingestion unscheduled.

## 2026-06-12 - Macro cluster saves roll back partial member failures

- Reason: `save_macro_cluster()` inserted the cluster row before inserting member rows, but lacked rollback handling; a member insert failure could leave a partial uncommitted cluster visible on the shared connection and vulnerable to a later unrelated commit.
- Change: Wrap macro cluster and member inserts in a single transactional try/rollback boundary.
- Verification: Added a DB regression that forces a member binding failure after cluster insertion and asserts no cluster is visible afterward; full gates are run after this note.
- Impact: Protects canonical cluster/digest state from partial macro snapshots when member persistence fails mid-write.

## 2026-06-12 - Report JSON rejects NaN and Infinity

- Reason: Pipeline report artifacts used default `json.dump()`, which can write non-standard `NaN`/`Infinity` tokens and leave operator-facing report files that fail strict JSON tooling.
- Change: Write report artifacts with `allow_nan=False` while preserving the existing atomic `.tmp` + `os.replace` behavior.
- Verification: Added a pipeline regression proving non-standard report payloads fail and leave no `.tmp` or final `.json` artifact; full gates are run after this note.
- Impact: Keeps generated report files standards-compliant and prevents malformed analysis artifacts from being saved or exported.
