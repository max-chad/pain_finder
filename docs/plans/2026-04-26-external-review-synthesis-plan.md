# External Review Synthesis Implementation Plan

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task. Each implementation PR must be test-first, additive-only for SQLite migrations, and must run the OpenClaw validation commands before PR update.

**Goal:** Turn `pain_finder` into an evidence-backed B2B opportunity intelligence tool for self-directed research: recurring pain clusters, verified quotes, buyer/WTP signals, competitor failures, normalized frequency, confidence, and decision-ready research reports.

**Architecture:** Keep the current Python + SQLite + Telegram/Hermes + `.docx`/CSV workflow, but move the decision unit from individual posts to verified pain clusters. Add first-class comments, ingestion coverage/cursors, deterministic evidence verification, high-recall candidate generation, staged LLM extraction, real/stable embeddings, calibrated scoring, rich local reports, and a feedback/evaluation loop.

**Tech Stack:** Python, SQLite/JSON1, `pytest`, `ruff`, current OpenAI-compatible LLM client (`openrouter.py`), optional DSPy parser, existing Reddit/HN/review ingestors, current `.docx` digest builder, optional local/static HTML report surface, optional embedding backends through the existing `embedder.py`/provider routing.

---

## Source material

- Verbatim-ish extracted review: `docs/reviews/2026-04-26-external-pain-finder-review-extract.md`
- This plan intentionally treats the review’s product/technical theses as true.
- User-requested deviation from the review: **do not implement compliance/legal/SaaS-readiness work now**. This is a private self-research tool, not a public SaaS.

## Explicit non-goals

The following review items are excluded from the implementation scope for now:

- Reddit legal review / express written approval / licensed-provider strategy.
- SaaS compliance model, public Terms, legal stance docs, commercial data-access policy.
- SaaS pricing, seats, onboarding, SSO, enterprise features, public beta/commercial pilot mechanics.
- Audit logs whose only purpose is legal/compliance posture.
- “No raw Reddit redistribution” product-policy work, except where the same change is useful for research quality.

The following data-hygiene items remain **in scope** because they improve research quality, not because of compliance:

- deletion/removal/body availability flags;
- `author_hash` for unique-author/frequency metrics;
- source method and coverage tracking;
- source links and quote provenance.

## Current baseline to preserve

Do not regress these existing strengths while implementing the review:

- `scraper.py`: Reddit fallback cascade (`PRAW → OAuth JSON → public JSON → RSS`), retry/backoff, feed mix, subreddit search queries, top comments/full-thread fetch.
- `classifier.py` / `openrouter.py`: B2B-oriented fields already exist in some form (`post_type`, `first_handness`, `buyer_authority`, `evidence_spans`, component scores, comment-market counters).
- `pipeline.py`: budget pause checks, prescreen counters, opportunity bucket enrichment, deep-dive trigger matrix, report persistence.
- `db.py`: additive SQLite migrations, WAL/synchronous/busy-timeout/foreign-key reliability, usage/cost ledger, macro cluster tables.
- `digest_delivery.py`: grouped `.docx` digest with canonical cluster section.
- `eval_harness.py`: seed evaluation flow, even though the dataset is too small.
- Existing Google Sheets/CSV export and GTM generation should remain available, but GTM should not distract from evidence/cluster/report quality.

## Central diagnosis from the review

The project is already more than a crawler. The weak point is not “can it fetch posts?” but whether it can produce **decision-grade, repeatable, auditable opportunity evidence**. The product should stop competing as a generic “Reddit pain finder” and become a B2B research engine:

```text
niche → verified pain clusters → evidence → opportunity score → next research actions
```

Every major implementation choice below serves that path.

## Thesis coverage matrix

| Review thesis | Plan response | Scope status |
| --- | --- | --- |
| Position as evidence-backed B2B opportunity intelligence, not generic Reddit scraper | Rename/report copy and README/product framing around verified B2B workflow failures and research reports | In scope |
| Direct competitors exist; differentiation must be deeper than AI Reddit summaries | Evidence verifier, benchmark transparency, buyer/WTP intelligence, competitor failure radar, multi-source triangulation | In scope |
| Preserve ingestion fallbacks, top comments, structured B2B scoring, budgets, eval harness | Regression tests and preservation checklist in every wave | In scope |
| Recall is cut before LLM by narrow keywords | High-recall candidate generation, semantic retrieval, screening false-negative metrics | In scope |
| DSPy schema is not aligned with full product schema | Full schema parity for DSPy/OpenAI-compatible path, schema-versioned outputs | In scope |
| Evidence spans are not verified | Deterministic exact/fuzzy evidence verifier with source location, match confidence, and score penalty/drop | In scope |
| Hash BoW clustering is unstable | Real/stable embeddings, cluster problem statements, representative examples, stability score | In scope |
| Benchmark is too small | Expand eval set, label guide, hard negatives, baseline comparisons, ablations, MVP thresholds | In scope |
| Comments are not first-class | Add `comments` table, structured comment fetch, author hashes, consensus/workaround/tool signals | In scope |
| Frequency is not normalized | Per-source/subreddit activity baselines and pain mentions per 1,000 posts/comments | In scope |
| UX is developer-first | Add cluster cards, score breakdown, coverage/confidence report, rejected/noise examples, source drilldown | In scope as local/static/report UX |
| Need feedback loop and active learning | Add feedback table + Telegram/report buttons + eval ingestion | In scope |
| Competitor failure radar is strategic | Build competitor/tool complaint cluster view | In scope |
| Research-to-action workflow is strategic | Add interview questions, ICP hypothesis, wedge, messaging suggestions per cluster | In scope |
| Multi-source triangulation strengthens signals | Combine Reddit/HN/reviews in cluster evidence and scoring | In scope |
| Compliance/legal Reddit commercial model | Excluded per user instruction | Out of scope now |

---

# Delivery strategy

## PR structure

Implement as a sequence of safe PRs, not one monster diff:

1. **PR A — Evidence + schema parity quick wins**
2. **PR B — Comments/cursors/coverage data foundation**
3. **PR C — Eval benchmark + metrics expansion**
4. **PR D — High-recall staged classifier + scoring calibration**
5. **PR E — Stable clustering + verified cluster cards**
6. **PR F — Local research UX + feedback loop**
7. **PR G — Strategic features: competitor radar, triangulation, research-to-action**
8. **PR H — Hardening audit + final regression/documentation pass**

If the user has not reviewed an open PR, stack follow-up commits into that PR instead of opening a parallel PR.

## Validation commands for every PR

Run the repo-registered OpenClaw checks from `/etc/openclaw/repos.yaml`:

```bash
ruff check .
pytest --cov=. --cov-fail-under=80 -q
test -f .env || cp .env.example .env; docker compose config -q
```

Focused commands while iterating:

```bash
pytest tests/test_classifier.py -q
pytest tests/test_openrouter.py -q
pytest tests/test_pipeline.py -q
pytest tests/test_db.py -q
pytest tests/test_scraper.py -q
pytest tests/test_clusterer.py -q
pytest tests/test_eval_harness.py -q
pytest tests/test_digest_delivery.py -q
```

Eval smoke after relevant waves:

```bash
python eval/run_eval.py --dataset eval/seed_posts.jsonl --labels eval/labels.jsonl --output-dir reports/eval/smoke
```

---

# Wave 0 — Baseline and test reliability

## Task 0.1: Record current baseline before changing behavior

**Objective:** Create a reproducible baseline so later improvements are measured, not guessed.

**Files:**
- Create: `docs/reports/2026-04-26-review-baseline.md`
- Modify only if needed: `eval/README.md`

**Steps:**
1. Run `ruff check .` and record result.
2. Run `pytest --cov=. --cov-fail-under=80 -q` and record duration/failures.
3. Run current eval smoke and record metrics.
4. Record current config defaults that affect quality: `CLASSIFIER_MODE`, `SCREEN_MIN_RULE_SCORE`, `DSPY_REDDIT_PARSER_ENABLED`, `TREND_*`, `DEEP_DIVE_*`.

**Acceptance:** Baseline doc exists and cites exact commands/results.

## Task 0.2: Fix local validation if it still times out or lacks tools

**Objective:** Remove the review’s “green tests could not be confirmed” uncertainty.

**Files:**
- Modify: `requirements.txt` if missing required dev/test dependency.
- Modify: `scripts/lint.sh`, `scripts/test.sh`, `scripts/build.sh` if they diverge from repo checks.
- Test: existing test suite.

**Implementation notes:**
- Prefer project-local `.venv` tools if present.
- Do not weaken coverage threshold.
- If a test is slow, profile and split/mark it only with a clear reason; do not skip to make the suite green.

**Acceptance:** Full validation commands complete locally.

---

# Wave 1 — Evaluation foundation and label discipline

## Task 1.1: Add a label guide for the expanded taxonomy

**Objective:** Make labels consistent before expanding the benchmark.

**Files:**
- Create: `eval/label_guide.md`
- Modify: `eval/labels.schema.json`
- Modify: `eval/README.md`
- Test: `tests/test_eval_harness.py`

**Required label fields:**
- `is_pain`
- `is_monetizable`
- `post_type`
- `pain_type`
- `expression_type`
- `first_handness`
- `buyer_authority`
- `intensity_label`
- `urgency_label`
- `wtp_label`
- `current_workaround`
- `incumbent_failure`
- `evidence_quality`
- `opportunity_type`
- `is_current_opportunity`
- `hard_negative_type`
- `expected_cluster_key` where known

**Acceptance:** Schema validates existing labels and new examples; docs define positive/negative examples.

## Task 1.2: Expand hard negatives first

**Objective:** Catch false positives before optimizing for recall.

**Files:**
- Modify: `eval/seed_posts.jsonl`
- Modify: `eval/labels.jsonl`
- Test: `tests/test_eval_harness.py`

**Data target:** Add at least 50 hard negatives before larger collection:
- generic recommendation questions;
- generic opinions;
- B2C/consumer rants;
- solved issues;
- founder pitches;
- news/analysis threads;
- vendor comparisons without operational consequence;
- low-context complaints.

**Acceptance:** Eval harness reports false-positive rate and screening false-negative rate by hard-negative type.

## Task 1.3: Add evidence and cluster metrics to the eval harness

**Objective:** Evaluate the actual moat: verified evidence and clusters.

**Files:**
- Modify: `eval_harness.py`
- Modify: `eval/run_eval.py`
- Modify: `eval/README.md`
- Test: `tests/test_eval_harness.py`

**Metrics to add:**
- `evidence_exact_match_rate`
- `evidence_coverage`
- `evidence_relevance` placeholder/manual label support
- `source_link_validity` placeholder/manual label support
- `cluster_duplicate_rate`
- `cluster_purity` for labeled cluster keys
- `top_n_useful_rate` if feedback labels are available
- `cost_per_useful_insight` when usage events are provided
- `latency_ms_per_prediction` optional artifact field

**Acceptance:** Offline predictions can produce all metrics deterministically, with `null`/`not_applicable` only when the needed labels are genuinely absent.

## Task 1.4: Add baseline comparison mode

**Objective:** Compare current pipeline, no-prescreen, rules-only, LLM-only, DSPy vs non-DSPy instead of relying on vibes.

**Files:**
- Modify: `eval/run_eval.py`
- Modify: `eval_harness.py`
- Create: `eval/baselines.example.yaml` or documented CLI examples in `eval/README.md`
- Test: `tests/test_eval_harness.py`

**Acceptance:** A single command can write separate metrics artifacts per baseline under `reports/eval/<run_id>/`.

---

# Wave 2 — Evidence-first schema and deterministic verifier

## Task 2.1: Add evidence source model and verifier module

**Objective:** Enforce “no quote, no insight.”

**Files:**
- Create: `evidence.py`
- Test: `tests/test_evidence.py`

**Core types:**

```python
@dataclass(frozen=True)
class EvidenceSource:
    source_type: str  # title|body|comment
    text: str
    post_id: str
    comment_id: str | None = None
    permalink: str = ""
    created_utc: int | None = None

@dataclass(frozen=True)
class VerifiedEvidence:
    quote: str
    source_type: str
    post_id: str
    comment_id: str | None
    permalink: str
    match_type: str  # exact|fuzzy|none
    match_confidence: float
```

**Verifier behavior:**
1. Normalize whitespace and punctuation but preserve quote text.
2. Try exact substring match in title/body/comments.
3. Try fuzzy match only if exact fails.
4. Attach source location, permalink, post/comment id, timestamp when available.
5. Drop or mark `match_type='none'` for unverifiable spans.

**Acceptance:** Unit tests cover exact title/body/comment matches, fuzzy whitespace/punctuation variants, false hallucinated spans, duplicate quotes, and empty evidence.

## Task 2.2: Store verified evidence and evidence quality

**Objective:** Make evidence auditable in DB, exports, digests, and eval.

**Files:**
- Modify: `db.py`
- Modify: `classifier.py`
- Modify: `openrouter.py`
- Modify: `pipeline.py`
- Modify: `export_sheets.py`
- Modify: `digest_delivery.py`
- Test: `tests/test_db.py`
- Test: `tests/test_classifier.py`
- Test: `tests/test_openrouter.py`
- Test: `tests/test_pipeline.py`
- Test: `tests/test_digest_delivery.py`

**Additive DB fields:**
- `verified_evidence_json TEXT DEFAULT '[]'`
- `evidence_quality TEXT DEFAULT 'no_quote'`
- `evidence_match_rate REAL DEFAULT 0`
- `confidence REAL DEFAULT 0`
- `uncertainty_reason TEXT DEFAULT ''`
- `needs_human_review INTEGER DEFAULT 0`

**Quality mapping:**
- `no_quote`: no evidence spans or no verified matches.
- `weak_quote`: one weak/fuzzy match.
- `exact_quote`: at least one exact verified quote.
- `multi_quote`: two or more verified quotes.
- `linked_multi_source`: verified quotes from more than one independent post/source inside a cluster.

**Acceptance:** Insights without verified evidence are demoted or marked `needs_human_review`; digest/export shows evidence quality and confidence.

## Task 2.3: Align OpenAI-compatible and DSPy schemas

**Objective:** Stop DSPy primary path from silently defaulting critical fields.

**Files:**
- Modify: `openrouter.py`
- Modify: `dspy_parser.py`
- Modify: `classifier.py`
- Test: `tests/test_openrouter.py`
- Test: `tests/test_dspy_parser.py`
- Test: `tests/test_classifier.py`

**Schema fields required on both paths:**
- Existing: `post_type`, `first_handness`, `buyer_authority`, `evidence_spans`.
- Add: `pain_type`, `expression_type`, `user_context`, `intensity`, `frequency`, `urgency`, `current_workaround`, `incumbent_failure`, `evidence_quality`, `opportunity_type`, `confidence`, `uncertainty_reason`, `needs_human_review`.

**Acceptance:** Parser tests prove DSPy and OpenAI-compatible paths return the same canonical `AnalysisResult` fields or fail closed with explicit fallback reason.

## Task 2.4: Enforce evidence-first promotion rules

**Objective:** Keep attractive but unsupported summaries out of top reports.

**Files:**
- Modify: `pipeline.py`
- Modify: `classifier.py`
- Modify: `digest_delivery.py`
- Test: `tests/test_pipeline.py`
- Test: `tests/test_digest_delivery.py`

**Rules:**
- No verified quote → cannot appear in Top Opportunities; can appear in “Needs Review / Weak signals.”
- Verified exact quote + first-hand/buyer signal → eligible for top ranking.
- Evidence match rate participates in `opportunity_score`.
- Store `evidence_rejection_reason` in `score_components_json` when demoted.

**Acceptance:** Tests show hallucinated/unmatched evidence loses ranking even if LLM returns high WTP.

---

# Wave 3 — First-class comments, ingestion cursors, and coverage

## Task 3.1: Add first-class comment model

**Objective:** Stop treating comments as anonymous text snippets; measure consensus and workarounds properly.

**Files:**
- Modify: `scraper.py`
- Create or modify: `comments.py` if keeping comment dataclasses separate is cleaner.
- Test: `tests/test_scraper.py`

**Comment fields:**
- `comment_id`
- `post_id`
- `parent_id`
- `body`
- `body_hash`
- `author_hash`
- `score`
- `created_utc`
- `depth`
- `is_op`
- `is_deleted`
- `permalink`
- `fetched_at`

**Acceptance:** PRAW/OAuth/public JSON full-thread paths return structured comments; old `top_comments: list[str]` remains backward-compatible as a derived sample.

## Task 3.2: Persist comments and deletion/body availability

**Objective:** Enable consensus, unique-author, and source-validity calculations.

**Files:**
- Modify: `db.py`
- Modify: `pipeline.py`
- Test: `tests/test_db.py`
- Test: `tests/test_pipeline.py`

**Add tables/fields:**
- `comments` table with the fields above.
- `pain_points.is_deleted INTEGER DEFAULT 0`
- `pain_points.is_removed INTEGER DEFAULT 0`
- `pain_points.body_available INTEGER DEFAULT 1`
- `pain_points.deleted_detected_at TEXT`
- `pain_points.author_hash TEXT`

**Acceptance:** Insert/upsert is idempotent; deleted/removed posts do not break evidence verification; author hashes support unique-author counts without raw usernames.

## Task 3.3: Add ingestion cursor and coverage tables

**Objective:** Make coverage measurable and pagination resumable.

**Files:**
- Modify: `db.py`
- Modify: `scraper.py`
- Modify: `pipeline.py`
- Modify: `scheduler.py`
- Test: `tests/test_db.py`
- Test: `tests/test_scraper.py`
- Test: `tests/test_pipeline.py`

**Tables:**

```sql
source_ingestion_cursors(
  id INTEGER PRIMARY KEY,
  source TEXT NOT NULL,
  subreddit TEXT,
  feed TEXT,
  query TEXT,
  timeframe TEXT,
  after TEXT,
  before TEXT,
  time_window TEXT,
  last_seen_created_utc INTEGER,
  last_success_at TEXT,
  fetch_errors_json TEXT DEFAULT '[]',
  UNIQUE(source, subreddit, feed, query, timeframe)
)

source_coverage_runs(
  id INTEGER PRIMARY KEY,
  source TEXT NOT NULL,
  scope TEXT NOT NULL,
  fetched_posts INTEGER DEFAULT 0,
  fetched_comments INTEGER DEFAULT 0,
  skipped_deleted INTEGER DEFAULT 0,
  skipped_duplicates INTEGER DEFAULT 0,
  failed_requests INTEGER DEFAULT 0,
  source_method_used TEXT,
  duration_ms INTEGER,
  created_at TEXT DEFAULT (datetime('now'))
)
```

**Acceptance:** Every analysis report can state source method, fetched/skipped counts, and fetch failures.

## Task 3.4: Implement normalized frequency metrics

**Objective:** Make “10 pains in r/SaaS” comparable to “10 pains in r/smallbusiness.”

**Files:**
- Modify: `db.py`
- Modify: `pipeline.py`
- Modify: `clusterer.py`
- Modify: `digest_delivery.py`
- Test: `tests/test_db.py`
- Test: `tests/test_clusterer.py`
- Test: `tests/test_digest_delivery.py`

**Metrics:**
- `pain_mentions_per_1000_posts`
- `pain_mentions_per_1000_comments`
- `unique_authors_count`
- `unique_threads_count`
- `weekly_delta`
- `source_activity_baseline`

**Acceptance:** Cluster cards show frequency normalized by source activity, not just raw mention count.

---

# Wave 4 — High-recall candidate generation and staged LLM pipeline

## Task 4.1: Relax keyword prescreen into high-recall screening

**Objective:** Avoid dropping real pain before LLM/classifier sees it.

**Files:**
- Modify: `classifier.py`
- Modify: `config.py`
- Modify: `.env.example`
- Test: `tests/test_classifier.py`
- Test: `tests/test_config.py`

**Implementation notes:**
- Keep deterministic rules but bias for recall.
- Add semantic indicators for operational consequence: reconciliation, sync, export, handoff, manual work, deadline, switching, workaround, pricing lock-in.
- Ensure “Does anyone have a sane way to reconcile Shopify payouts with QuickBooks?” passes even without explicit “hate/problem/wish”.
- Track `screening_false_negative_count` in eval.

**Acceptance:** Hard negative precision remains measurable, but seeded hidden-pain examples pass screening.

## Task 4.2: Add semantic candidate retrieval

**Objective:** Supplement keywords with embeddings/semantic queries.

**Files:**
- Modify: `classifier.py`
- Modify: `embedder.py`
- Modify: `pipeline.py`
- Test: `tests/test_classifier.py`
- Test: `tests/test_embedder.py`
- Test: `tests/test_pipeline.py`

**Implementation notes:**
- Use existing embedding provider abstraction if available.
- Add deterministic lightweight fallback for tests.
- Add semantic query prototypes for workflow failures, tool switching, manual workarounds, paid workaround, competitor pricing/support issues.
- Keep budget caps: semantic retrieval must not cause unbounded LLM calls.

**Acceptance:** Candidate count and dropped-count metrics prove screening is high-recall and bounded.

## Task 4.3: Split extraction into staged schemas

**Objective:** Reduce hallucinated all-in-one prompt behavior.

**Files:**
- Modify: `openrouter.py`
- Modify: `classifier.py`
- Modify: `pipeline.py`
- Test: `tests/test_openrouter.py`
- Test: `tests/test_classifier.py`
- Test: `tests/test_pipeline.py`

**Stages:**
1. `pain_detection_v1`: pain/noise, post type, operational consequence.
2. `evidence_extraction_v1`: quote candidates only.
3. `opportunity_classification_v1`: B2B context, buyer authority, WTP, urgency, workaround, incumbent failure.
4. `score_explanation_v1`: compact score components only if prior stages pass.
5. Existing deep-dive and cluster-label stages remain separate.

**Acceptance:** Usage events contain schema version and candidate stage; invalid-output retries/fallbacks are counted.

## Task 4.4: Add confidence and human-review routing

**Objective:** Admit uncertainty instead of over-ranking ambiguous items.

**Files:**
- Modify: `openrouter.py`
- Modify: `classifier.py`
- Modify: `pipeline.py`
- Modify: `digest_delivery.py`
- Test: `tests/test_openrouter.py`
- Test: `tests/test_classifier.py`
- Test: `tests/test_pipeline.py`

**Acceptance:** Low-confidence items go to “Needs Review / Weak Signals” and do not contaminate top clusters.

---

# Wave 5 — Multi-axis taxonomy and calibrated opportunity scoring

## Task 5.1: Persist the full multi-axis pain taxonomy

**Objective:** Move beyond `complaint/unsolved/wish` while preserving compatibility.

**Files:**
- Modify: `classifier.py`
- Modify: `openrouter.py`
- Modify: `db.py`
- Modify: `pipeline.py`
- Modify: `export_sheets.py`
- Test: `tests/test_classifier.py`
- Test: `tests/test_openrouter.py`
- Test: `tests/test_db.py`

**Fields:**
- `pain_type`: workflow friction, missing feature, reliability issue, integration gap, pricing pain, support failure, switching/lock-in, reporting/data gap, security/risk, procurement friction, knowledge gap.
- `expression_type`: complaint, solution_request, workaround, comparison, feature_request, churn_signal, budget_signal, same_here_consensus.
- `user_context_json`: role, industry, company size, tool stack, process, seniority, geography.
- `intensity_score` 0..1.
- `frequency_signal`: single, thread_consensus, repeated_cross_thread, trend.
- `urgency`: none, mild, deadline, active_blocker, revenue_critical, security_risk.
- `current_workaround`: none, manual, spreadsheet, Zapier, paid_tool, agency, custom_script.
- `wtp_score` 0..1 while keeping existing 0..10 `willingness_to_pay` for compatibility.
- `incumbent_failure`: none, weak, explicit_competitor_failure, switching.
- `opportunity_type`: micro-SaaS, feature, integration, service, content, marketplace, automation, API/tooling.

**Acceptance:** Exports and reports can filter by all new axes.

## Task 5.2: Rebuild opportunity score with visible components

**Objective:** Make ranking explainable and calibratable.

**Files:**
- Modify: `classifier.py`
- Modify: `pipeline.py`
- Modify: `db.py`
- Modify: `digest_delivery.py`
- Modify: `export_sheets.py`
- Test: `tests/test_classifier.py`
- Test: `tests/test_pipeline.py`
- Test: `tests/test_digest_delivery.py`

**Baseline score formula:**

```text
Opportunity Score =
  0.18 * intensity
+ 0.14 * frequency
+ 0.14 * willingness_to_pay
+ 0.12 * buyer_authority
+ 0.10 * current_workaround
+ 0.10 * incumbent_failure
+ 0.08 * urgency
+ 0.08 * evidence_quality
+ 0.06 * recency
- penalties(noise, shill_risk, solved_by_obvious_tool, stale_discussion)
```

**Acceptance:** `score_components_json` contains every factor and penalty; reports explain “why this score.”

## Task 5.3: Calibrate scoring using eval artifacts

**Objective:** Stop tuning weights by intuition.

**Files:**
- Create: `eval/calibrate_score.py`
- Modify: `eval/README.md`
- Test: `tests/test_eval_harness.py` or new `tests/test_score_calibration.py`

**Implementation notes:**
- Start with grid/manual calibration; no heavyweight ML unless necessary.
- Optimize for Top-N useful insight rate, monetizable precision, and evidence exact match.
- Output recommended weights to a JSON artifact; do not auto-apply without review.

**Acceptance:** Calibration script emits deterministic artifacts on fixture data.

---

# Wave 6 — Stable embeddings and verified pain clusters

## Task 6.1: Replace hash BoW as the normal clustering path

**Objective:** Make clustering stable enough for research decisions.

**Files:**
- Modify: `clusterer.py`
- Modify: `embedder.py`
- Modify: `config.py`
- Modify: `.env.example`
- Test: `tests/test_clusterer.py`
- Test: `tests/test_embedder.py`

**Implementation notes:**
- Primary path: existing embedding provider abstraction / real embeddings.
- Test fallback: deterministic `hashlib`-based embedding, not Python `hash()`.
- Keep old 96-dim hash BoW only as `EMBED_PROVIDER=emergency_hash_bow` with warning.

**Acceptance:** Same input produces same cluster assignments across process restarts in tests.

## Task 6.2: Cluster problem statements, not raw posts

**Objective:** Group recurring problems instead of similar wording.

**Files:**
- Modify: `clusterer.py`
- Modify: `pipeline.py`
- Modify: `db.py`
- Test: `tests/test_clusterer.py`
- Test: `tests/test_db.py`

**Problem statement input should combine:**
- normalized pain summary;
- verified evidence snippets;
- current workaround;
- incumbent failure;
- persona/context;
- source/domain tags.

**Acceptance:** Tests show unrelated posts with generic “manual spreadsheet problem” text do not merge unless evidence/problem statements match.

## Task 6.3: Add cluster stability and representative examples

**Objective:** Make clusters auditable.

**Files:**
- Modify: `clusterer.py`
- Modify: `db.py`
- Modify: `digest_delivery.py`
- Test: `tests/test_clusterer.py`
- Test: `tests/test_digest_delivery.py`

**Fields:**
- `cluster_stability_score`
- `representative_examples_json`
- `verified_quote_count`
- `independent_source_count`
- `unique_author_count`
- `normalized_frequency_json`

**Acceptance:** Cluster cards show representative examples and stability/quality, not only generated labels.

## Task 6.4: Add cluster eval metrics

**Objective:** Prevent false merges and duplicate clusters.

**Files:**
- Modify: `eval_harness.py`
- Modify: `eval/run_eval.py`
- Test: `tests/test_eval_harness.py`

**Acceptance:** Fixture data can compute duplicate rate and cluster purity from `expected_cluster_key` labels.

---

# Wave 7 — Local research UX and reports

## Task 7.1: Make cluster cards the primary `.docx` digest surface

**Objective:** A researcher should read clusters first, posts second.

**Files:**
- Modify: `digest_delivery.py`
- Modify: `db.py` query helpers if needed.
- Test: `tests/test_digest_delivery.py`

**Cluster card contents:**
- title;
- opportunity score;
- confidence;
- normalized frequency;
- intensity;
- WTP;
- urgency;
- buyer authority;
- why it matters;
- verified evidence quotes with links;
- affected users/personas;
- current workarounds;
- competitors/tools mentioned;
- suggested wedge;
- risks;
- score breakdown;
- coverage/confidence block.

**Acceptance:** Daily digest can produce “Top 20 pain clusters for one niche, each with verified quotes, score breakdown, and confidence.”

## Task 7.2: Add a local static HTML research report

**Objective:** Provide dashboard-like review without turning this into SaaS.

**Files:**
- Create: `report_builder.py`
- Create: `templates/research_report.html` or inline minimal template if the repo avoids template deps.
- Modify: `pipeline.py` or `main.py` only if wiring is needed.
- Test: `tests/test_report_builder.py`

**Sections:**
- Top opportunities.
- Trending pains.
- Competitor failures.
- Unmet feature requests.
- High-WTP signals.
- Weak signals to watch.
- Rejected/noise examples.
- Coverage and confidence report.

**Filters in static report:** source, subreddit/source, time range, pain type, industry/persona, intensity, WTP, urgency, confidence, first-hand only, buyer authority, competitor, current/evergreen, evidence quality.

**Acceptance:** HTML artifact renders from fixture DB data without external services.

## Task 7.3: Show rejected/noise examples

**Objective:** Build trust by showing what was intentionally discarded.

**Files:**
- Modify: `pipeline.py`
- Modify: `db.py`
- Modify: `digest_delivery.py`
- Modify: `report_builder.py`
- Test: `tests/test_pipeline.py`
- Test: `tests/test_digest_delivery.py`
- Test: `tests/test_report_builder.py`

**Acceptance:** Reports include a bounded list of rejected/noise items with reason: generic question, consumer rant, low context, no evidence, solved issue, shill risk, duplicate.

## Task 7.4: Add feedback loop

**Objective:** Turn user judgment into eval/active-learning data.

**Files:**
- Modify: `db.py`
- Modify: `bot.py`
- Modify: `digest_delivery.py` if report embeds feedback IDs.
- Modify: `eval_harness.py`
- Test: `tests/test_db.py`
- Test: `tests/test_bot.py`
- Test: `tests/test_eval_harness.py`

**Feedback values:**
- `useful`
- `not_a_pain`
- `duplicate`
- `too_generic`
- `wrong_segment`
- `bad_evidence`

**Acceptance:** Feedback is stored, visible in `/status` or a report section, and can be exported as eval labels or label-review queue.

## Task 7.5: Keep exports research-friendly

**Objective:** Make exports useful without SaaS work.

**Files:**
- Modify: `export_sheets.py`
- Optional create: `export_notion.py` only if Notion credentials are already available/configured.
- Modify: `README.md`
- Test: existing export tests or new `tests/test_export_sheets.py` / `tests/test_export_notion.py`.

**Acceptance:** CSV/Sheets include verified evidence, score breakdown, cluster key, confidence, coverage fields, and feedback status.

---

# Wave 8 — Strategic differentiators

## Task 8.1: Competitor Failure Radar

**Objective:** Surface recurring complaints about specific tools.

**Files:**
- Modify: `db.py`
- Modify: `clusterer.py`
- Modify: `digest_delivery.py`
- Modify: `report_builder.py`
- Test: `tests/test_db.py`
- Test: `tests/test_clusterer.py`
- Test: `tests/test_digest_delivery.py`

**Signals:**
- pricing pain;
- missing features;
- lock-in/switching;
- reliability/support failure;
- workaround mentions;
- alternative-tool mentions;
- churn/switching language.

**Acceptance:** Report has a “Competitor failures” section grouped by tool, with verified quotes and cluster links.

## Task 8.2: Multi-source triangulation

**Objective:** Upgrade weak single-source pain into stronger cross-source evidence.

**Files:**
- Modify: `clusterer.py`
- Modify: `db.py`
- Modify: `scraper_hn.py`
- Modify: `scraper_reviews.py`
- Modify: `pipeline.py`
- Test: `tests/test_clusterer.py`
- Test: `tests/test_db.py`
- Test: tests for HN/review scrapers if present, otherwise add them.

**Acceptance:** Cluster quality improves when Reddit + HN + reviews mention the same problem; source diversity is visible in the score breakdown.

## Task 8.3: Buyer/WTP intelligence report

**Objective:** Answer “is this a buyer or just someone shouting online?”

**Files:**
- Modify: `classifier.py`
- Modify: `pipeline.py`
- Modify: `digest_delivery.py`
- Modify: `report_builder.py`
- Test: `tests/test_classifier.py`
- Test: `tests/test_pipeline.py`

**Acceptance:** Cluster cards show buyer role distribution, WTP evidence, paid workaround evidence, and uncertainty.

## Task 8.4: Research-to-action workflow

**Objective:** Convert pain clusters into the next research action.

**Files:**
- Modify: `openrouter.py`
- Modify: `pipeline.py`
- Modify: `db.py`
- Modify: `digest_delivery.py`
- Modify: `report_builder.py`
- Test: `tests/test_openrouter.py`
- Test: `tests/test_pipeline.py`

**Per-cluster actions:**
- interview questions;
- ICP hypothesis;
- MVP wedge;
- messaging angle;
- “why now”;
- risks/unknowns;
- suggested manual validation step.

**Acceptance:** Top clusters include a concise “Next research action” block, not just passive summaries.

---

# Wave 9 — Final hardening audit

## Task 9.1: Full regression and quality audit

**Objective:** Match the user’s expected pre-use hardening session.

**Files:**
- Create: `docs/reports/YYYY-MM-DD-hardening-audit.md`
- Modify tests/docs only if gaps are found.

**Checklist:**
- Full OpenClaw validation passes.
- Eval metrics meet or explicitly miss target thresholds.
- Evidence exact match target checked.
- Cluster duplicate rate checked.
- Runtime config defaults are fail-safe for budget and source limits.
- No raw secrets in docs/examples.
- Reports include coverage/confidence and rejected/noise examples.
- DB migrations are additive-only and backward-compatible.
- README documents the self-research workflow.

## Task 9.2: MVP target thresholds

Implementation should not be considered “usable” until these are measured on the expanded benchmark or explicitly waived:

- Pain precision: `>= 0.75`
- Pain recall: `>= 0.60`
- Evidence exact match: `>= 0.95`
- Monetizable precision: `>= 0.65`
- Top-10 useful insight rate: `>= 0.50`
- Cluster duplicate rate: `<= 0.20`

---

# Immediate next execution order

1. Commit this source extract + plan as a docs-only PR.
2. Run full validation despite docs-only changes.
3. Start implementation with **PR A / Wave 2 quick wins**:
   - evidence verifier module;
   - verified evidence DB fields;
   - DSPy/OpenAI-compatible schema parity;
   - evidence-first promotion rules.
4. Then implement **Wave 1 eval hard negatives/metrics** before making classifier behavior more aggressive.
5. Only after evidence + eval are reliable, proceed to first-class comments/cursors and high-recall semantic retrieval.

## Blocker criteria

- If tests cannot complete locally, pause feature work and fix validation first.
- If evidence verifier drops too much due source mismatch, report examples and adjust matching; do not bypass verification.
- If high-recall screening increases false positives without eval visibility, stop and expand hard negatives before tuning.
- If clustering remains unstable after real/stable embeddings, keep cluster output analyst-facing only and do not make it the primary digest.
- If LLM schema invalid-output rate spikes after schema expansion, split the stage further rather than accepting defaults.
