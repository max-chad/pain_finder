# pain_finder

Telegram-controlled / Hermes-managed B2B pain discovery system with Reddit, Hacker News, and review-source ingestion, deep-dive enrichment, macro trend clustering, budget guardrails, GTM generation, and daily grouped digest delivery.

## What It Does

- Collects candidate pain posts from:
  - Reddit (`scraper.py`)
  - Hacker News Algolia API (`scraper_hn.py`)
  - Configured review pages (`scraper_reviews.py`)
- Classifies pain with `legacy|b2b|dual` modes and strict JSON schemas.
- Defaults the full LLM stack (primary parse, legacy fallback, deep dive, clustering, GTM, embeddings) to Codex/OpenAI-compatible routing, with OpenRouter-compatible env aliases still supported.
- For `openai-codex` / ChatGPT Codex backend calls, the runtime now mirrors Codex CLI request headers (`originator`, Codex-style `User-Agent`, `ChatGPT-Account-ID`) so quota/account routing stays on the Codex path instead of generic ChatGPT handling.
- Can route the primary Reddit pain parse through an optional DSPy/Codex (`gpt-5.3-spark`, `high`) backend, with the same provider defaults.
- Tracks monetization signals (`pain_level`, `willingness_to_pay`, `is_monetizable`, `niche_category`, `competitor_tags`).
- Auto-runs deep dives on high-value signals and supports manual deep dives.
- Runs macro trend clustering over historical high-signal items.
- Enforces daily LLM budget caps with pause/resume runtime flags.
- Generates GTM assets (names, hero copy, MVP features, pricing, positioning) for selected pain points.
- Exports filtered data to CSV and optionally upserts to Google Sheets.
- Can run in `APP_MODE=hermes`, which disables Telegram polling conflicts and publishes a once-daily grouped `.docx` digest back through the configured bot token/chat.

## Architecture

- `main.py`: wires services, scheduler jobs, Telegram app lifecycle.
- `db.py`: async SQLite layer, PRAGMAs, additive migrations, analytics helpers.
- `scraper.py`: Reddit scraping with PRAW + OAuth JSON + public JSON fallback, plus RSS fallback when Reddit blocks unauthenticated JSON; supports mixed feed ingestion (`new+rising+top`), optional subreddit pain-search queries, top comments, full thread extraction, retry/backoff.
- `scraper_hn.py`: Hacker News Algolia ingestion.
- `scraper_reviews.py`: review-source scraping for negative (1-2 star) reviews.
- `openrouter.py`: provider-agnostic OpenAI-compatible LLM client (Codex/OpenAI/OpenRouter), strict schema parsing, usage/cost accounting.
- `classifier.py`: scoring + classification mode orchestration + competitor tag normalization, with optional DSPy primary Reddit parser fallback.
- `pipeline.py`: ingestion->classification->persistence->deep dive->digest flow.
- `clusterer.py`: hybrid local embedding clustering + LLM trend labels.
- `budget.py`: daily spend checks, pause state, override-to-next-UTC-day resume.
- `generator_gtm.py`: one-click GTM payload generation and persistence.
- `export_sheets.py`: CSV writer + optional Google Sheets push.
- `digest_delivery.py`: `.docx` daily digest builder grouped by niche/source/category tags.
- `scheduler.py`: monitored subreddit jobs + macro/HN/review jobs.
- `bot.py`: Telegram command handlers and inline callback actions.
- `eval_harness.py` + `eval/run_eval.py`: reproducible hand-labeled evaluation flow for the Reddit parser (live Codex/DSPy or offline saved predictions).

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
- `LLM_API_KEY` (or backward-compatible `OPENAI_API_KEY` / `OPENROUTER_API_KEY`)

Core provider + models:

- `LLM_PROVIDER` (default `codex`)
- `LLM_API_BASE`
- `LLM_MODEL`
- `LLM_DEEP_DIVE_MODEL` (falls back to `LLM_MODEL`)
- `LLM_CLUSTER_MODEL` (falls back to `LLM_MODEL`)
- `LLM_GTM_MODEL` (falls back to `LLM_MODEL`)
- `LLM_MODEL_PRICING_JSON`
- `LLM_REASONING_EFFORT`
- `LLM_TEMPERATURE`
- `LLM_MAX_TOKENS`

Backward-compatible aliases still work:

- `OPENROUTER_API_KEY`
- `OPENROUTER_MODEL`
- `OPENROUTER_DEEP_DIVE_MODEL`
- `OPENROUTER_CLUSTER_MODEL`
- `OPENROUTER_GTM_MODEL`
- `OPENROUTER_MODEL_PRICING_JSON`

Classifier/deep dive controls:

- `CLASSIFIER_MODE` (`legacy|b2b|dual`, default `dual`)
- `CLASSIFIER_MAX_CONCURRENCY` (default `8`)
- `LLM_MAX_CLASSIFICATIONS_PER_RUN` (default `0`, disabled when `0`; set >0 to cap classifications per analysis run)
- `DEEP_DIVE_WTP_THRESHOLD` (default `8`)
- `DEEP_DIVE_MAX_COMMENTS` (default `250`)

Scraper controls:

- `SCRAPER_TOP_COMMENTS` (default `5`)
- `SCRAPER_COMMENT_FETCH_CONCURRENCY` (default `8`)
- `SCRAPER_RETRY_MAX_ATTEMPTS` (default `5`)
- `SCRAPER_RETRY_BASE_DELAY` (default `1.0`)
- `SCRAPER_FEED_MIX_JSON` (default `["new", "rising", "top"]`)
- `SCRAPER_SEARCH_QUERIES_JSON` (optional pain-intent subreddit search queries merged with feed results)

Optional DSPy Reddit parser:

- `DSPY_REDDIT_PARSER_ENABLED` (default `0`; set to `1` after installing `requirements-dspy.txt`)
- `DSPY_PROVIDER` (defaults to `LLM_PROVIDER`, so Codex by default)
- `DSPY_MODEL` (defaults to `LLM_MODEL`)
- `DSPY_REASONING_EFFORT` (defaults to `LLM_REASONING_EFFORT`)
- `DSPY_API_KEY` (defaults to `LLM_API_KEY` / `OPENAI_API_KEY`)
- `DSPY_API_BASE` (defaults to `LLM_API_BASE`)
- `DSPY_TEMPERATURE`
- `DSPY_MAX_TOKENS`

The DSPy dependency is intentionally optional and is not installed by the base requirements. Install it only when this parser path is needed:

```bash
pip install -r requirements-dspy.txt
```

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
- `REVIEW_TARGETS_JSON` (enabled targets must have `site`, `name`, and a public `http`/`https` `url`; localhost/private IP targets are rejected)
- `REVIEWS_MAX_PER_TARGET`
- `REVIEWS_INTERVAL_HOURS`

Budget and runtime guardrails:

- `DAILY_BUDGET_USD`

Export:

- `EXPORT_MIN_WTP`
- `GOOGLE_SHEETS_CREDENTIALS_JSON`
- `GOOGLE_SHEETS_SPREADSHEET_ID`
- `GOOGLE_SHEETS_WORKSHEET_PREFIX`

Hermes-mode delivery:

- `APP_MODE` (`telegram` or `hermes`)
- `DIGEST_DELIVERY_ENABLED`
- `DIGEST_HOURS`
- `DIGEST_GROUP_BY` (`niche|source|category`)
- `DIGEST_HOUR_UTC`
- `DIGEST_MINUTE_UTC`
- `DIGEST_MIN_WTP`
- `DIGEST_MAX_ITEMS_PER_GROUP`

Codex reserve routing note:

- True reserve-credential selection requires more than one `openai-codex` credential in Hermes (`hermes auth add openai-codex --type oauth --label reserve`).
- With only one Codex credential in Hermes, runtime fixes can align request headers and account routing, but they cannot invent a separate reserve credential.

Paths and source auth:

- `DB_PATH`
- `REPORTS_DIR`
- `REDDIT_CLIENT_ID`
- `REDDIT_CLIENT_SECRET`
- `REDDIT_USER_AGENT`
- `EMBED_PROVIDER`
- `EMBED_API_KEY`
- `EMBED_API_BASE`
- `EMBED_MODEL`

## Data Model Highlights

- `pain_points`: canonical signals, source tag, competitor tags, triage/deep-dive/GTM context.
- `pain_point_competitors`: normalized `(post_id, competitor_tag)` map.
- `deep_dives`: deep-dive payload lifecycle per post.
- `analysis_runs`: per-run metrics.
- `macro_trend_runs`, `macro_trend_clusters`, `macro_trend_members`: macro analytics snapshots.
- `llm_usage_events`: token/cost ledger.
- `runtime_flags`: `llm_paused`, pause reason/day, resume override.
- `monitored_subreddits`: active subreddit schedules plus last success, last attempt, and last error for `/list` diagnostics.
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

Optional local embedding model fallback (heavier install):

```bash
pip install -r requirements-ml.txt
```

## Docker

```bash
docker compose up -d --build
```

The image includes a local Docker healthcheck (`python healthcheck.py`) that validates required environment parsing, report-directory writability, and read-only access to an already initialized SQLite database without calling external APIs or running migrations.
The runtime handles `SIGTERM`/`SIGINT` through the asyncio loop so Docker stops and manual interrupts drain through scheduler/database cleanup.

Persisted mounts in `docker-compose.yml`:

- `./data -> /app/data` (`DB_PATH=/app/data/pain_finder.db`)
- `./reports -> /app/reports`

## Source Smoke Checks

Use the read-only source smoke check before a first data-collection run or after changing source env. It fetches source posts and prints JSON, but does not call LLMs, Telegram, database writes, exports, or schedulers.

```bash
python smoke_collect.py --source reddit --subreddit python --limit 5
python smoke_collect.py --source hn --hn-keyword "manual process" --limit 5
python smoke_collect.py --source all --limit 5
```

Add `--require-posts` when a deployment gate should fail if a requested source returns zero posts. The script intentionally reads only source-related env (`REDDIT_*`, `SCRAPER_*`, `HN_*`, `REVIEW_TARGETS_JSON`, `REVIEWS_MAX_PER_TARGET`) and does not require Telegram or LLM credentials. Reddit subreddit names are validated before network calls, and review targets must be public `http`/`https` URLs.

## Quality Gates

```bash
ruff check .
mypy db.py scraper.py openrouter.py classifier.py pipeline.py bot.py scheduler.py export_sheets.py main.py healthcheck.py smoke_collect.py url_safety.py dspy_parser.py eval/run_eval.py eval_harness.py
docker compose config -q
python -m pip_audit -r requirements.txt
pytest --cov=. --cov-fail-under=80 -q
```

## Evaluation Harness

The Reddit parser now has a checked-in hand-labeled starter eval set under `eval/`.

Run live against the configured runtime (Codex/OpenAI + optional DSPy):

```bash
python eval/run_eval.py \
  --dataset eval/seed_posts.jsonl \
  --labels eval/labels.jsonl \
  --live \
  --output-dir eval/artifacts/seed-live \
  --reference-now-ts 1776729600
```

Or rescore a saved predictions file without making API calls:

```bash
python eval/run_eval.py \
  --dataset eval/seed_posts.jsonl \
  --labels eval/labels.jsonl \
  --predictions-path eval/artifacts/seed-live/predictions.jsonl \
  --output-dir eval/artifacts/seed-rescore \
  --reference-now-ts 1776729600
```

Metrics currently include:
- pain precision / recall / f1
- monetizable precision / recall / f1
- stale leakage rate
- screening false negatives
- post-type confusion
- first-handness accuracy
- buyer-authority accuracy

For labeling rules and the seed-set caveats, see `eval/README.md`.

## Upgrade Notes

- Gemini upgrade (Phases 1-4 + initial aggressive improvements): `docs/changes/2026-02-24-gemini-upgrade.md`
- Expansion upgrade (Phases 5-8): `docs/changes/2026-02-24-phase5-8-expansion.md`
