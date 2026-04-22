# Pain pipeline v2 implementation plan

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task.

**Goal:** Upgrade `pain_finder` from post-level pain scoring to a fresher, typed, evidence-backed opportunity pipeline that separates current opportunities from evergreen pains, uses cheaper screening before expensive LLM calls, and is measurable with an evaluation harness.

**Architecture:** Introduce a two-stage pipeline: (1) deterministic/source-aware ingestion + cheap screening + post typing, (2) strict JSON LLM enrichment only for shortlisted candidates, followed by cluster-level aggregation and digest rendering. Persist source timestamps, evidence spans, first-handness, buyer authority, comment-market signals, and ranking features in the DB so downstream ranking, clustering, and evaluation do not depend on re-prompting.

**Tech Stack:** Python, SQLite/JSON1, Reddit JSON/PRAW/RSS fallback, existing OpenRouter/Codex runtime, current test stack (`pytest`, `ruff`), optional embeddings/BOW fallback.

---

## Current context / verified findings

### Local code inspection
- `scraper.py` `Post` stores `post_id/subreddit/title/body/url/score/permalink/top_comments/source`, but **does not store source post timestamp** (`created_utc`) or author metadata.
- `classifier.py` currently uses a single early keyword gate plus one `PainSignal` schema with only:
  - `category` in `{complaint, unsolved, wish}`
  - `summary`, `severity`, `is_monetizable`, `pain_level`, `willingness_to_pay`, `niche_category`, `competitor_tags`
- `openrouter.py` primary prompt returns only that compact schema. There are **no evidence spans, first-handness, buyer authority, workflow frequency, consensus, stale flag, or solved flag** fields.
- `pipeline.py` inserts post-level rows and immediately ranks digests by `round((pain + wtp)/2)`. Deep dives are only triggered by `is_monetizable && willingness_to_pay >= DEEP_DIVE_WTP_THRESHOLD`.
- `db.py` currently filters recency via local `created_at` (ingest time), not source post time. `llm_usage_events` only stores `model, operation, prompt_tokens, completion_tokens, cost_usd, post_id`.
- `clusterer.py` already exists, but clustering is based on post-level text (`title + summary + deep_dive_summary + competitors`) and a tiny hash-BOW embedding. It does **not** produce canonical pain clusters with recency/incumbent/comment consensus aggregates.
- There is **no evaluation harness** for manual labels, freshness error, or confusion matrix by post type.

### Research findings
- Official PRAW docs confirm `Submission.created_utc` is available as Unix time. We can therefore store real source age instead of relying on local insertion time.
- Official PRAW docs confirm subreddit search supports `sort` and `time_filter`. Even if public/RSS fallbacks are used, the data model should retain source timestamps so age gates can work consistently across acquisition paths.
- Official SQLite JSON1 docs confirm `json_extract()` / `json_each()` are available. This makes it reasonable to store typed evidence spans, comment signals, and score components as structured JSON during the transition period without exploding the number of columns immediately.
- Browser-based web search is currently blocked in this environment because Playwright Chromium is not installed; preflight research therefore relies on official docs fetched via terminal plus local source inspection.

### Important operational note
- The large isolated run that produced `deep_dive_count = 0` used `DEEP_DIVE_WTP_THRESHOLD=99` intentionally to suppress deep dives during reserve-model load testing. That zero count was expected for that run and should not be treated as the baseline production behavior.

## Explicit non-goals
- Do **not** redesign Telegram delivery mode in this slice.
- Do **not** introduce heavyweight infra (separate DB service, queue, or external vector DB) unless SQLite/JSON1 proves insufficient.
- Do **not** collapse every improvement into one giant commit; ship as narrow, test-backed slices.

## Proposed rollout order
1. Source age + current-opportunity vs evergreen split.
2. Post-type taxonomy + first-handness + buyer authority + evidence spans.
3. Cheap screening before expensive LLM classification.
4. Composite ranking formula + comment-market signals.
5. Canonical pain clustering.
6. Evaluation harness + observability hardening.
7. Deep-dive trigger redesign and re-enable.

---

## Task 1: Persist source timestamps and split current vs evergreen

**Objective:** Stop treating ingest time as source recency and introduce a hard age gate for current opportunities.

**Files:**
- Modify: `scraper.py`
- Modify: `db.py`
- Modify: `pipeline.py`
- Modify: `export_sheets.py`
- Modify: `config.py`
- Test: `tests/test_scraper.py`
- Test: `tests/test_db.py`
- Test: `tests/test_pipeline.py`

**Implementation notes:**
- Extend `Post` with at least:
  - `source_created_at: str | None`
  - `source_created_ts: int | None`
  - `author_name: str | None = None`
- Populate source timestamps in all Reddit acquisition paths:
  - PRAW (`submission.created_utc`)
  - OAuth JSON / public JSON (`created_utc` field)
  - RSS (`published/updated` if available)
- Add DB fields to `pain_points` (prefer explicit columns for hot filters):
  - `source_created_at TEXT`
  - `source_created_ts INTEGER`
  - `opportunity_bucket TEXT DEFAULT 'current_opportunity'`
- Add config/env:
  - `CURRENT_OPPORTUNITY_MAX_AGE_DAYS` default `180`
  - `EVERGREEN_MAX_AGE_DAYS` optional `365`
- Bucket logic:
  - if source age <= gate → `current_opportunity`
  - otherwise → `evergreen_pain`
- Digest/export methods must allow filtering by bucket so current and evergreen are rendered separately.

**Validation:**
- Test that fresh and stale posts with different `source_created_ts` land in different buckets.
- Test that `get_recent_pain_points()` can optionally filter by bucket and source age, not only local `created_at`.
- Test RSS/PRAW/JSON parsing preserves timestamps.

---

## Task 2: Add pre-score post typing and authority signals

**Objective:** Stop applying one pain/WTP scale to incompatible post genres.

**Files:**
- Modify: `classifier.py`
- Modify: `openrouter.py`
- Modify: `db.py`
- Modify: `pipeline.py`
- Test: `tests/test_classifier.py`
- Test: `tests/test_openrouter.py`
- Test: `tests/test_db.py`

**Implementation notes:**
- Replace current `{complaint, unsolved, wish}`-first logic with explicit post-type classification before monetization scoring.
- Introduce enums/validated strings for at least:
  - `first_person_pain`
  - `solution_request`
  - `founder_pitch`
  - `news_analysis`
  - `tool_comparison`
  - `advice_thread`
  - `vendor_rant`
- Add structured fields to `PainSignal` / `AnalysisResult` / DB:
  - `post_type`
  - `first_handness` (e.g. `first_hand`, `second_hand`, `aggregated`, `speculative`)
  - `buyer_authority` (e.g. `intern`, `ic`, `manager`, `head_of_ops`, `founder_owner`, `agency_operator`, `unknown`)
  - `buyer_authority_score` (normalized numeric helper for ranking)
- Make type-specific scoring rules:
  - `founder_pitch`, `news_analysis`, and generic `advice_thread` should be demoted by default unless strong first-hand evidence exists.
  - `vendor_rant` and `tool_comparison` can stay monetizable but require evidence of workflow failure and switching pain.

**Validation:**
- Unit tests for prompt parsing and schema validation of the new fields.
- Tests that `founder_pitch` / `news_analysis` do not get the same default WTP treatment as `first_person_pain`.

---

## Task 3: Require evidence spans and penalize unsupported claims

**Objective:** Prevent attractive summaries with weak grounding.

**Files:**
- Modify: `openrouter.py`
- Modify: `classifier.py`
- Modify: `db.py`
- Modify: `pipeline.py`
- Test: `tests/test_openrouter.py`
- Test: `tests/test_classifier.py`
- Test: `tests/test_db.py`

**Implementation notes:**
- Extend primary JSON schema with compact evidence fields:
  - `evidence_spans: ["..."]` (1-3 short quoted fragments)
  - `workflow_breakage: "..."`
  - `current_workaround: "..."`
  - `impact_signal: "time|money|risk|none"`
- Enforce hard limits in prompt + parser:
  - max 3 spans
  - each span capped to ~160 chars
  - JSON only; no freeform rationale
- If no valid evidence span is returned, reduce confidence / opportunity score, and optionally block promotion into `current_opportunity`.

**Validation:**
- Parser rejects missing or oversized evidence.
- Ranking logic explicitly penalizes missing evidence.

---

## Task 4: Introduce cheap screening and reduce token burn

**Objective:** Stop sending every vaguely complaint-like post to the expensive LLM path.

**Files:**
- Modify: `classifier.py`
- Modify: `openrouter.py`
- Modify: `config.py`
- Modify: `pipeline.py`
- Test: `tests/test_classifier.py`
- Test: `tests/test_pipeline.py`

**Implementation notes:**
- Split pipeline into stages:
  1. deterministic/rule-based prescreener
  2. optional embeddings/minor model shortlist
  3. full LLM enrichment only for shortlisted candidates
- Add config knobs:
  - `SCREEN_MIN_RULE_SCORE`
  - `SCREEN_MAX_LLM_CANDIDATES_PER_RUN`
  - `PRIMARY_MAX_OUTPUT_TOKENS`
- Keep prompt JSON strict and short; remove verbose one-sentence explanations where a smaller field will do.
- Log how many posts are dropped at each gate.

**Validation:**
- Regression test showing LLM candidate count is lower than fresh post count when cheap stage is enabled.
- Ensure valid pain posts are still retained in tests.

---

## Task 5: Replace naive digest ranking with composite opportunity score

**Objective:** Rank by investment relevance, not just average of pain and WTP.

**Files:**
- Modify: `classifier.py`
- Modify: `pipeline.py`
- Modify: `db.py`
- Modify: `export_sheets.py`
- Test: `tests/test_pipeline.py`
- Test: `tests/test_db.py`

**Implementation notes:**
- Persist atomic factors needed for ranking:
  - `workflow_frequency_score`
  - `impact_score`
  - `consensus_score`
  - `incumbent_failure_score`
  - `recency_score`
  - `stale_penalty`
  - `solved_penalty`
  - `opportunity_score`
- Initial formula can be approximate but explicit, e.g.:
  - `score = pain * buyer_authority * recency * workflow_frequency * impact * consensus * incumbent_failure - stale_penalty - solved_penalty`
- Store `score_components_json` for debugability.
- Digest/export sorting should use `opportunity_score` first, then tie-break by evidence and recency.

**Validation:**
- Deterministic tests for ranking order with fixed score components.
- Digest test should show current-opportunity and evergreen sections sorted correctly.

---

## Task 6: Parse comments as market signal, not just deep-dive context

**Objective:** Promote consensus/workaround/shill detection into first-class ranking inputs.

**Files:**
- Modify: `scraper.py`
- Modify: `classifier.py`
- Modify: `openrouter.py`
- Modify: `db.py`
- Modify: `pipeline.py`
- Test: `tests/test_scraper.py`
- Test: `tests/test_classifier.py`
- Test: `tests/test_pipeline.py`

**Implementation notes:**
- Preserve a compact comment sample in the post or analysis payload instead of only appending comments to the body string.
- Add derived comment-market fields:
  - `comment_consensus_count`
  - `comment_same_here_count`
  - `comment_workaround_count`
  - `comment_tool_mentions`
  - `comment_shill_risk`
- Use a cheap extractor first (regex/counts for `same here`, tool names, promo patterns), then optional LLM summarization for shortlisted threads.
- Make comment signals influence `consensus_score`, `incumbent_failure_score`, and `solved_penalty`.

**Validation:**
- Tests for comment parsing from thread JSON.
- Tests that “same here” and workaround-heavy threads rank differently.

---

## Task 7: Move from post clustering to canonical pain clusters

**Objective:** Make the decision unit a recurring problem, not a single Reddit post.

**Files:**
- Modify: `clusterer.py`
- Modify: `db.py`
- Modify: `openrouter.py`
- Modify: `pipeline.py`
- Test: `tests/test_clusterer.py`
- Test: `tests/test_db.py`

**Implementation notes:**
- Replace/augment current macro trend cluster output with canonical pain-cluster fields:
  - `canonical_key`
  - `cluster_label`
  - `cluster_summary`
  - `fresh_post_count`
  - `evergreen_post_count`
  - `median_buyer_authority`
  - `incumbents_json`
  - `avg_opportunity_score`
  - `latest_source_created_ts`
- Use cluster membership to aggregate:
  - frequency
  - freshness
  - company/operator types
  - dominant incumbents
  - recurring workarounds
- Digest should eventually render clusters first, posts second.

**Validation:**
- Tests that multiple posts about the same pain collapse into one canonical cluster summary.
- Tests that unrelated posts with similar generic wording do not merge too aggressively.

---

## Task 8: Build evaluation harness with hand labels

**Objective:** Stop arguing with persuasive text and start arguing with metrics.

**Files:**
- Create: `eval/README.md`
- Create: `eval/seed_posts.jsonl`
- Create: `eval/labels.schema.json` (optional)
- Create: `eval/run_eval.py`
- Create: `tests/test_eval_harness.py`
- Modify: `README.md`

**Implementation notes:**
- Create a reproducible evaluation set of 100-150 posts.
- Label at least:
  - `is_pain`
  - `is_monetizable`
  - `post_type`
  - `is_current_opportunity`
  - `first_handness`
  - `buyer_authority`
- Compute:
  - `precision@pain`
  - `precision@monetizable`
  - freshness error / stale leakage
  - confusion matrix for post types
  - optional calibration summary for `opportunity_score`
- Store predictions and metrics artifacts under `reports/eval/` or `eval/artifacts/`.

**Validation:**
- Harness runs from CLI with fixed input and produces deterministic metric JSON.

---

## Task 9: Harden logging and fallback observability

**Objective:** Make prompt-path drift and silent fallback visible.

**Files:**
- Modify: `openrouter.py`
- Modify: `db.py`
- Modify: `pipeline.py`
- Test: `tests/test_openrouter.py`
- Test: `tests/test_db.py`

**Implementation notes:**
- Extend `llm_usage_events` (or add sibling table) with:
  - `prompt_hash`
  - `fallback_reason`
  - `schema_version`
  - `request_path` / `provider`
  - `candidate_stage` (screening, primary, deep_dive, cluster, etc.)
- Log per-run counters for:
  - prescreen dropped
  - primary succeeded
  - legacy fallback invoked
  - invalid-schema retries
  - deep-dive skipped by reason
- Make schema version explicit in prompts/parsers so migrations are auditable.

**Validation:**
- Tests for usage-event inserts with prompt hash and fallback reason.
- Run log assertions in pipeline tests.

---

## Task 10: Re-enable deep dives with better triggers

**Objective:** Restore the “interesting post → investable hypothesis” step in a controlled way.

**Files:**
- Modify: `pipeline.py`
- Modify: `openrouter.py`
- Modify: `config.py`
- Modify: `db.py`
- Test: `tests/test_pipeline.py`
- Test: `tests/test_openrouter.py`

**Implementation notes:**
- Replace the single `willingness_to_pay >= threshold` trigger with a richer policy:
  - current-opportunity only OR top evergreen clusters with strong consensus
  - minimum evidence count
  - minimum buyer authority
  - comment consensus / incumbent failure trigger
  - per-run cap to protect budget
- Persist `deep_dive_skip_reason` when a row is not deep-dived.
- Ensure the large-run smoke path can still disable deep dives intentionally via config without looking like accidental failure.

**Validation:**
- Tests for deep-dive trigger matrix and skip reasons.
- Confirm non-zero deep dives in a targeted integration test when trigger conditions are met.

---

## Suggested implementation slices / commit order
1. `feat(data): persist source timestamps and opportunity buckets`
2. `feat(classifier): add post taxonomy authority and evidence schema`
3. `feat(screening): add cheap candidate gate before primary LLM`
4. `feat(ranking): add composite opportunity score`
5. `feat(comments): derive comment consensus and workaround signals`
6. `feat(clusterer): build canonical pain clusters`
7. `feat(eval): add labeled evaluation harness`
8. `feat(observability): log prompt hashes fallback reasons and schema version`
9. `feat(deep-dive): re-enable triggered deep dives with explicit skip reasons`

## Validation commands
- `ruff check .`
- `pytest --cov=. --cov-fail-under=80 -q`
- Focused tests while iterating:
  - `pytest tests/test_scraper.py -q`
  - `pytest tests/test_classifier.py -q`
  - `pytest tests/test_openrouter.py -q`
  - `pytest tests/test_pipeline.py -q`
  - `pytest tests/test_clusterer.py -q`
  - `pytest tests/test_db.py -q`
- Eval harness smoke:
  - `python eval/run_eval.py --dataset eval/seed_posts.jsonl --labels eval/labels.jsonl`

## Risks / tradeoffs
- Adding many explicit DB columns improves filtering/debugging, but too many low-value columns will bloat migrations. Use columns for hot filters and JSON for secondary diagnostics.
- Comment parsing can blow up tokens if naïvely concatenated. Keep compact stats and short excerpts; avoid sending the entire thread unless the post already passed screening.
- Canonical clustering quality will be capped by the current hash-BOW embedder. If clustering remains noisy after better features, replace that embedder rather than endlessly tuning the threshold.
- Evaluation will require hand-labeling discipline. Without a stable labeling guide, metric drift will be noisy and hard to trust.

## Blocker criteria
- If source timestamps cannot be recovered reliably for one acquisition path, mark those rows as `unknown_age` and exclude them from `current_opportunity` until fixed.
- If schema expansion causes LLM invalid-output rate to spike, split the prompt into a small typed-stage schema first and move long-tail fields to deep dive.
- If cluster false merges remain high after evidence-aware features, pause cluster-first digest rollout and keep clusters as analyst-facing only until evaluation improves.
