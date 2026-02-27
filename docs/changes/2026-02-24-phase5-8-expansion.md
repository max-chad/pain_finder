# 2026-02-24 Phase 5-8 Expansion

## Section A: Requested Phase 5-8 Scope Delivered

### Phase 5: Macro-Trend Aggregation

- Added `clusterer.py` with `MacroTrendClusterer.run(window_days)` and persisted run/cluster/member outputs.
- Added hybrid local-embedding clustering with configurable similarity threshold.
- Added optional LLM cluster labeling via OpenRouter cluster schema.
- Added `/macro [days]` command and scheduled weekly macro job wiring.

### Competitor Tracking

- Added `competitor_tags` to primary analysis schema and parsing.
- Added classifier normalization for competitor tags (lowercase, dedup, trim, length guard).
- Added normalized competitor table `pain_point_competitors` and lookup helpers.

### Phase 6: Multi-Source Ingestion

- Added `scraper_hn.py` (HN Algolia API).
- Added `scraper_reviews.py` (direct review scraping adapters for negative reviews).
- Added canonical source-prefixed post IDs (`reddit:`, `hn:`, `review:`) in shared flow.
- Routed external posts through existing classifier + persistence pipeline.
- Added scheduler hooks and runtime wiring for HN/review ingestion jobs.

### Phase 7: Cost Control and Token Economics

- Extended OpenRouter client usage parsing and per-call cost estimation from `OPENROUTER_MODEL_PRICING_JSON`.
- Added LLM usage ledger table `llm_usage_events` and DB APIs for spend totals.
- Added runtime pause flags table `runtime_flags` and pause/resume semantics.
- Added `budget.py` guard service enforcing `DAILY_BUDGET_USD` across LLM operations.
- Added `/budget` and `/resume` Telegram commands.
- Scheduler reload now respects pause state and skips LLM jobs while paused.

### Phase 8: Autonomous GTM Prep

- Added `generator_gtm.py` for one-click GTM package generation.
- Added strict GTM schema handling in `openrouter.py`.
- Added `gtm_assets` persistence.
- Added `/gtm <post_id>` command and inline GTM callback action.

## Section B: Extra Aggressive Improvements Completed

- Hardened callback payload parsing for IDs containing `:`.
- Added stronger test coverage for new modules and runtime paths.
- Added end-to-end main wiring test for macro/HN/reviews job execution.
- Fixed decimal rating parsing in review adapter.
- Expanded scheduler tests for pause-aware and multi-job behavior.

## Section C: Known Limitations and Next Backlog

- Review source parsing is heuristic and may require site-specific adapter updates when markup changes.
- Local embedding clustering is lightweight; semantic quality can be improved with dedicated embedding APIs.
- Budget reset currently follows UTC daily boundary; timezone-specific budget windows are not yet supported.
- Suggested backlog:
  - Add per-source circuit breaker and retry budgets.
  - Add dedup fingerprints across cross-source near-duplicate complaints.
  - Add Telegram query command for competitor-tag drilldowns.
  - Add job-level health dashboard endpoint or status snapshot export.
