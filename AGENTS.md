# AGENTS.md

Operational runbook for contributors and automation agents working on `pain_finder`.

## System Map

- `main.py`: dependency wiring, scheduler startup/reload, Telegram lifecycle, budget-pause alert callback.
- `bot.py`: Telegram command handlers and inline callbacks.
- `pipeline.py`: canonical ingestion/classification/deep-dive/digest orchestration.
- `classifier.py`: keyword gate + `legacy|b2b|dual` classifier behavior + competitor tag normalization.
- `openrouter.py`: strict schema calls (primary, deep dive, cluster label, GTM), usage/cost parsing.
- `budget.py`: runtime spending checks and pause/override logic.
- `clusterer.py`: macro trend clustering and label generation.
- `generator_gtm.py`: GTM asset generation from stored pain context.
- `scraper.py`: Reddit source (PRAW + JSON), top comments, full thread extraction, retry/backoff.
- `scraper_hn.py`: Hacker News Algolia source.
- `scraper_reviews.py`: review-source scraping adapters.
- `db.py`: schema/migrations and all persistence/query helpers.
- `export_sheets.py`: CSV export and optional Google Sheets upsert.
- `scheduler.py`: monitoring + macro + HN + review job lifecycle.

## Command Map

- `/analyze r/<subreddit> [limit]`
- `/monitor r/<subreddit> [Nh]`
- `/unmonitor r/<subreddit>`
- `/list`
- `/status`
- `/export [r/<subreddit>]`
- `/deepdive <post_id>`
- `/digest [r/<subreddit>] [hours]`
- `/macro [days]`
- `/budget`
- `/resume`
- `/gtm <post_id>`

Inline callbacks:

- `triage:favorite:<post_id>`
- `triage:discard:<post_id>`
- `deepdive:<post_id>:<subreddit>`
- `gtm:<post_id>:<source_scope>`

## Schema Map

Core:

- `pain_points`: canonical signal store.
  - Key fields: `post_id`, `source`, `is_monetizable`, `pain_level`, `willingness_to_pay`, `niche_category`, `competitor_tags`, `triage_status`, `deep_dive_status`, `deep_dive_summary`.
- `pain_point_competitors`: normalized competitor tags for lookup analytics.
- `deep_dives`: deep-dive payload lifecycle.
- `analysis_runs`: per-analysis run metrics.

Macro trends:

- `macro_trend_runs`
- `macro_trend_clusters`
- `macro_trend_members`

Budget/runtime:

- `llm_usage_events`: model, operation, token counts, cost, post link.
- `runtime_flags`: `llm_paused`, `pause_reason`, `pause_day`, `resume_override_until`.

GTM:

- `gtm_assets`: structured generated GTM payloads.

Support:

- `monitored_subreddits`, `reports`, `schema_migrations`.

## What Changed in This Upgrade (Phases 5-8)

Implemented items mapped to files:

- [x] Macro trend clustering module (`clusterer.py`).
- [x] Competitor mention tracking in primary schema and DB normalization (`openrouter.py`, `classifier.py`, `db.py`).
- [x] HN ingestion source (`scraper_hn.py`, `main.py`, `scheduler.py`, `pipeline.py`).
- [x] Review-source ingestion (`scraper_reviews.py`, `main.py`, `scheduler.py`, `pipeline.py`).
- [x] LLM usage ledger + model pricing + operation-level accounting (`openrouter.py`, `db.py`, `config.py`).
- [x] Daily budget guard and pause/resume runtime semantics (`budget.py`, `main.py`, `bot.py`, `scheduler.py`, `pipeline.py`).
- [x] `/macro`, `/budget`, `/resume`, `/gtm` commands (`bot.py`).
- [x] GTM generator service and persistence (`generator_gtm.py`, `openrouter.py`, `db.py`, `bot.py`).
- [x] New schema/tables/indexes under additive migration path (`db.py`).
- [x] Expanded integration tests and coverage gate validation (all `tests/test_*.py`).

Additional improvements beyond requested plan:

- [x] Callback parsing hardened for prefixed IDs containing `:` (`bot.py`).
- [x] Scheduler pause-check made mock-safe and type-safe (`scheduler.py`).
- [x] Review rating parser fixed for decimal rating strings (`scraper_reviews.py`).
- [x] Main wiring tests extended to execute macro/HN/review job paths (`tests/test_main.py`).

## Debug Playbooks

### 1) Reddit 429 or API storms

1. Check logs for `Reddit HTTP 429` and retry/backoff messages.
2. Increase `SCRAPER_RETRY_BASE_DELAY` or lower `SCRAPER_TOP_COMMENTS`.
3. Ensure `REDDIT_CLIENT_ID`/`REDDIT_CLIENT_SECRET` are set to prefer PRAW path.

### 2) OpenRouter failures or invalid JSON

1. Confirm `OPENROUTER_API_KEY` and model names.
2. Check for retries on 429/5xx in logs.
3. Keep `CLASSIFIER_MODE=dual` for fallback behavior when strict schema parse fails.
4. Verify budget state with `/budget` to ensure calls are not paused.

### 3) Budget cap reached incidents

1. Run `/budget` to verify `spent`, `cap`, and `LLM paused` state.
2. Decide whether to wait for UTC day reset or run `/resume`.
3. If frequent pauses occur, tune `DAILY_BUDGET_USD` and ingestion cadence.
4. Confirm scheduler reload happened after pause/resume (check scheduler logs).

### 4) Google Sheets export failures

1. Validate `GOOGLE_SHEETS_CREDENTIALS_JSON` parses as valid service-account JSON.
2. Validate `GOOGLE_SHEETS_SPREADSHEET_ID` and sharing permissions.
3. Confirm CSV still delivered; inspect warning text from `/export`.

### 5) SQLite lock/contention symptoms

1. Confirm PRAGMAs are active (`WAL`, `busy_timeout=5000`, `foreign_keys=ON`).
2. Ensure only one process writes the same DB file.
3. Check long-running operations and reduce synchronous blocking in handlers.

## Safe Rollout

1. Install/update dependencies: `pip install -r requirements.txt`.
2. Ensure new env vars are present (use `.env.example` as source of truth).
3. Run quality gate:
   - `ruff check .`
   - `mypy .`
   - `pytest --cov=. --cov-fail-under=80 -q`
4. Start service and smoke test in Telegram:
   - `/status`
   - `/analyze r/<subreddit> 10`
   - `/macro 30`
   - `/budget`
   - `/gtm <post_id>`
   - `/export`

## Rollback

1. Checkout previous stable commit/tag.
2. Keep DB file in place (migrations are additive).
3. Restart app and verify `/status` and `/analyze`.
4. If old build cannot read new env vars, remove only newly introduced keys.
