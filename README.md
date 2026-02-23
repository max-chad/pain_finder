# pain_finder

Telegram-controlled Reddit pain point scanner for complaints, unsolved problems, and feature wishes.

## What It Does

- Scrapes posts from a target subreddit using PRAW when credentials are available.
- Falls back to Reddit public JSON API when PRAW fails or credentials are missing.
- Filters likely pain posts with keyword scoring and enriches with OpenRouter.
- Stores pain points and report metadata in SQLite.
- Supports on-demand analysis and passive monitoring from Telegram commands.

## Architecture

- `scraper.py`: Reddit data collection (PRAW + public JSON fallback).
- `classifier.py`: keyword scoring + optional OpenRouter enrichment.
- `pipeline.py`: shared analysis pipeline and atomic report generation.
- `db.py`: SQLite schema and async CRUD helpers.
- `scheduler.py`: APScheduler wrapper for passive monitoring.
- `bot.py`: Telegram command parsing, auth, and responses.
- `main.py`: runtime wiring and process lifecycle.

## Setup

1. Create and activate a virtual environment.
2. Install dependencies:

```bash
pip install -r requirements.txt
```

3. Copy `.env.example` to `.env` and fill values:

```env
TELEGRAM_BOT_TOKEN=...
TELEGRAM_CHAT_ID=...
OPENROUTER_API_KEY=...

# Optional for PRAW path
REDDIT_CLIENT_ID=
REDDIT_CLIENT_SECRET=
REDDIT_USER_AGENT=pain_finder/1.0

# Optional runtime paths
DB_PATH=pain_finder.db
REPORTS_DIR=reports
```

## Run

```bash
python main.py
```

## Telegram Commands

- `/analyze r/<subreddit> [limit]`
- `/monitor r/<subreddit> [Nh]`
- `/unmonitor r/<subreddit>`
- `/list`
- `/status`
- `/export [r/<subreddit>]`

Defaults:

- `/analyze` limit defaults to `100` and must be `1..100`.
- `/monitor` interval defaults to `24h` and must be `1..168h`.

## Testing

```bash
pytest -q
```

Coverage:

```bash
pytest --cov=. --cov-report=term-missing -q
```

## Troubleshooting

- `Unauthorized/no bot response`:
  - Ensure `TELEGRAM_CHAT_ID` matches the chat where you send commands.
- `PRAW errors`:
  - Leave Reddit credentials empty to force public JSON fallback.
- `OpenRouter errors`:
  - Verify `OPENROUTER_API_KEY` and model name.
  - Transient 429/5xx responses are retried automatically with backoff.
- `No export file found`:
  - Run `/analyze` at least once and verify `REPORTS_DIR` exists.

## Notes

- Reports are written atomically (`.tmp` + `os.replace`) to avoid partial files.
- Monitoring jobs are reloaded automatically after `/monitor` and `/unmonitor`.
