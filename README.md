# pain_finder

Telegram-controlled B2B pain discovery system with Reddit, Hacker News, and review-source ingestion, deep-dive enrichment, macro trend clustering, budget guardrails, and GTM generation.

## What It Does

- Collects candidate pain posts from:
  - Reddit (`scraper.py`)
  - Hacker News Algolia API (`scraper_hn.py`)
  - Configured review pages (`scraper_reviews.py`)
- Classifies pain with `legacy|b2b|dual` modes and strict JSON schemas.
- Tracks monetization signals (`pain_level`, `willingness_to_pay`, `is_monetizable`, `niche_category`, `competitor_tags`).
- Auto-runs deep dives on high-value signals and supports manual deep dives.
- Runs macro trend clustering over historical high-signal items.
- Enforces daily LLM budget caps with pause/resume runtime flags.
- Generates GTM assets (names, hero copy, MVP features, pricing, positioning) for selected pain points.
- Exports filtered data to CSV and optionally upserts to Google Sheets.

## Architecture

- `main.py`: wires services, scheduler jobs, Telegram app lifecycle.
- `db.py`: async SQLite layer, PRAGMAs, additive migrations, analytics helpers.
- `scraper.py`: Reddit scraping with PRAW + OAuth JSON + public JSON fallback, mixed feed ingestion (`new+rising+top`), top comments, full thread extraction, retry/backoff.
- `scraper_hn.py`: Hacker News Algolia ingestion.
- `scraper_reviews.py`: review-source scraping for negative (1-2 star) reviews.
- `openrouter.py`: LLM client, strict schema parsing, usage/cost accounting.
- `classifier.py`: scoring + classification mode orchestration + competitor tag normalization.
- `pipeline.py`: ingestion->classification->persistence->deep dive->digest flow.
- `clusterer.py`: hybrid local embedding clustering + LLM trend labels.
- `budget.py`: daily spend checks, pause state, override-to-next-UTC-day resume.
- `generator_gtm.py`: one-click GTM payload generation and persistence.
- `export_sheets.py`: CSV writer + optional Google Sheets push.
- `scheduler.py`: monitored subreddit jobs + macro/HN/review jobs.
- `bot.py`: Telegram command handlers and inline callback actions.

## Telegram Commands

Existing:

- `/analyze r/<subreddit> [limit]`
- `/monitor r/<subreddit> [Nh]`
- `/unmonitor r/<subreddit>`
- `/list`
- `/status`
- `/export [r/<subreddit>]`
- `/deepdive <post_id>`
- `/digest [r/<subreddit>] [hours]`

Phase 5-8 additions:

- `/macro [days]`
- `/budget`
- `/resume`
- `/gtm <post_id>`

Inline actions on pain cards:

- `Save to Favorites`
- `Discard`
- `Deep Dive`
- `Generate GTM`

## Environment Variables

Required:

- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`
- `OPENROUTER_API_KEY`

Core models:

- `OPENROUTER_MODEL`
- `OPENROUTER_DEEP_DIVE_MODEL` (falls back to `OPENROUTER_MODEL`)
- `OPENROUTER_CLUSTER_MODEL` (falls back to `OPENROUTER_MODEL`)
- `OPENROUTER_GTM_MODEL` (falls back to `OPENROUTER_MODEL`)
- `OPENROUTER_MODEL_PRICING_JSON`

Classifier/deep dive controls:

- `CLASSIFIER_MODE` (`legacy|b2b|dual`, default `dual`)
- `CLASSIFIER_MAX_CONCURRENCY` (default `8`)
- `DEEP_DIVE_WTP_THRESHOLD` (default `8`)
- `DEEP_DIVE_MAX_COMMENTS` (default `250`)

Scraper controls:

- `SCRAPER_TOP_COMMENTS` (default `5`)
- `SCRAPER_COMMENT_FETCH_CONCURRENCY` (default `8`)
- `SCRAPER_RETRY_MAX_ATTEMPTS` (default `5`)
- `SCRAPER_RETRY_BASE_DELAY` (default `1.0`)
- `SCRAPER_FEED_MIX_JSON` (default `['new', 'rising', 'top']`)

Trend clustering:

- `MACRO_TREND_ENABLED`
- `TREND_LOOKBACK_DAYS`
- `TREND_MIN_CLUSTER_SIZE`
- `TREND_CLUSTER_SIMILARITY`
- `MACRO_TREND_WEEKDAY_UTC`
- `MACRO_TREND_HOUR_UTC`

HN ingestion:

- `HN_ENABLED`
- `HN_KEYWORDS_JSON`
- `HN_LOOKBACK_HOURS`
- `HN_MAX_POSTS`
- `HN_INTERVAL_HOURS`

Review ingestion:

- `REVIEWS_ENABLED`
- `REVIEW_TARGETS_JSON`
- `REVIEWS_MAX_PER_TARGET`
- `REVIEWS_INTERVAL_HOURS`

Budget and runtime guardrails:

- `DAILY_BUDGET_USD`

Export:

- `EXPORT_MIN_WTP`
- `GOOGLE_SHEETS_CREDENTIALS_JSON`
- `GOOGLE_SHEETS_SPREADSHEET_ID`
- `GOOGLE_SHEETS_WORKSHEET_PREFIX`

Paths and source auth:

- `DB_PATH`
- `REPORTS_DIR`
- `REDDIT_CLIENT_ID`
- `REDDIT_CLIENT_SECRET`
- `REDDIT_USER_AGENT`

## Data Model Highlights

- `pain_points`: canonical signals, source tag, competitor tags, triage/deep-dive/GTM context.
- `pain_point_competitors`: normalized `(post_id, competitor_tag)` map.
- `deep_dives`: deep-dive payload lifecycle per post.
- `analysis_runs`: per-run metrics.
- `macro_trend_runs`, `macro_trend_clusters`, `macro_trend_members`: macro analytics snapshots.
- `llm_usage_events`: token/cost ledger.
- `runtime_flags`: `llm_paused`, pause reason/day, resume override.
- `gtm_assets`: generated GTM payloads.

## Budget Guardrail Behavior

- Every LLM-dependent operation checks budget state first.
- Daily spend is aggregated from `llm_usage_events`.
- If cap is reached, runtime is paused and LLM-dependent scheduled jobs stop on reload.
- `/resume` sets a temporary override until the next UTC day boundary.

## Export Behavior

- `/export` always returns a CSV file.
- If Sheets credentials and spreadsheet ID are set, export also upserts to Sheets.
- Sheets failures do not block CSV; a warning message is returned.

## Setup and Run

```bash
pip install -r requirements.txt
python main.py
```

## Docker

```bash
docker compose up -d --build
```

Persisted mounts in `docker-compose.yml`:

- `./pain_finder.db -> /app/pain_finder.db`
- `./reports -> /app/reports`

## Quality Gates

```bash
ruff check .
mypy .
pytest --cov=. --cov-fail-under=80 -q
```

## Upgrade Notes

- Gemini upgrade (Phases 1-4 + initial aggressive improvements): `docs/changes/2026-02-24-gemini-upgrade.md`
- Expansion upgrade (Phases 5-8): `docs/changes/2026-02-24-phase5-8-expansion.md`
