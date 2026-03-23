# 2026-02-24 Gemini Upgrade

## Section A: Gemini Requested Improvements Completed

### Phase 1: Foundation

- Added SQLite reliability PRAGMAs (`WAL`, `synchronous=NORMAL`, `busy_timeout`, `foreign_keys`) in `db.py`.
- Added idempotent schema migration ledger (`schema_migrations`) and additive migration logic.
- Expanded `pain_points` schema and created `deep_dives` + `analysis_runs` tables.
- Added top-comment extraction in both scraper paths and appended to analysis payload.
- Added full-thread extraction method for deep dives.
- Implemented exponential retry/backoff with jitter and `Retry-After` handling for Reddit JSON API.

### Phase 2: Intelligence

- Added strict B2B analysis schema parsing in `openrouter.py`.
- Added strict deep-dive schema parsing in `openrouter.py`.
- Added classifier mode switching (`legacy|b2b|dual`) with B2C rejection guardrails.
- Added pipeline deep-dive auto-trigger based on monetization and WTP threshold.
- Persisted deep-dive outputs into `deep_dives` and mirrored concise summary to `pain_points`.
- Recorded analysis run metrics in `analysis_runs`.

### Phase 3: Telegram UX and Exports

- Added inline callback actions for favorite/discard/deep dive.
- Added `/deepdive <post_id>` command.
- Added `/digest [r/<subreddit>] [hours]` command.
- Added CSV + optional Google Sheets exporter with CSV fallback on Sheets failure.

### Phase 4: Deployment

- Added `Dockerfile` with non-root runtime.
- Added `docker-compose.yml` with DB/report persistence mounts and env loading.
- Added `.dockerignore`.

## Section B: Extra Aggressive Improvements Completed

- Added noise-control behavior: prioritize monetizable cards and skip discarded items in card notifications.
- Added weighted digest ranking and niche grouping.
- Added recurring blocker extraction from deep-dive summaries.
- Added CI quality gate for lint (`ruff`), type check (`mypy`), and coverage threshold (`80%`).
- Added stable structured log messages for scheduler and pipeline operations.

## Section C: Known Limitations and Next Backlog

- Deep-dive and primary analysis still depend on external model quality/latency.
- Google Sheets write path assumes valid service account JSON in environment.
- Full-thread extraction for very large Reddit discussions may still be truncated by `DEEP_DIVE_MAX_COMMENTS`.
- Suggested next backlog:
  - Add rate-limited queue for deep dives to smooth burst loads.
  - Add richer deduplication/clustering across similar pain points.
  - Add richer post-history analytics endpoint for longitudinal trend tracking.

