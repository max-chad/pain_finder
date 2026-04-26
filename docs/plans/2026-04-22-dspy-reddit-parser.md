# DSPy Reddit Pain Parser Implementation Plan

> **For Hermes:** Use the `test-driven-development` skill while executing this plan. Write failing tests first, then implement the smallest change that makes them pass.

**Goal:** Increase Reddit pain-signal recall and classification quality by adding search-query discovery to the scraper and an optional DSPy-powered Reddit parser configured for Codex / `gpt-5.3-spark` / `high` reasoning effort.

**Architecture:** Keep `main.py` as the composition root. Extend `scraper.py` to merge search-query hits with the existing mixed-feed ingestion, carrying `discovery_query` metadata on `Post`. Add a new `dspy_parser.py` module that lazily configures DSPy and returns `AnalysisResult` compatible with the existing classifier. Wire the classifier to prefer DSPy for primary Reddit parsing and fall back to the existing OpenRouter path when DSPy is disabled or unavailable.

**Tech Stack:** Python 3.12, httpx, pytest, DSPy (lazy import), existing OpenRouter client

---

### Task 1: Add config + failing tests for Reddit search discovery and DSPy defaults

**Objective:** Make the intended behavior explicit before implementation.

**Files:**
- Modify: `tests/test_config.py`
- Modify: `tests/test_scraper.py`
- Modify: `tests/test_classifier.py`
- Modify: `tests/test_main.py`
- Create: `tests/test_dspy_parser.py`

**Step 1: Write failing tests**
- Config test for:
  - `SCRAPER_SEARCH_QUERIES`
  - `DSPY_REDDIT_PARSER_ENABLED`
  - `DSPY_PROVIDER=codex`
  - `DSPY_MODEL=gpt-5.3-spark`
  - `DSPY_REASONING_EFFORT=high`
- Scraper test proving search results are merged/deduplicated and preserve `discovery_query`.
- Classifier test proving DSPy parser is tried before OpenRouter primary parsing.
- Main wiring test proving `run()` passes the DSPy parser into `Classifier`.
- DSPy parser tests proving prediction payloads are normalized into `AnalysisResult`.

**Step 2: Run focused tests to verify failure**
Run the new targeted tests individually and confirm they fail for the expected missing fields/wiring.

---

### Task 2: Implement Reddit search-query discovery

**Objective:** Improve recall beyond `top/new/rising` by searching within the subreddit for pain-intent phrases.

**Files:**
- Modify: `config.py`
- Modify: `scraper.py`
- Modify: `pipeline.py`
- Modify: `README.md`
- Modify: `.env.example`

**Step 1: Implement minimal search-query config and `Post` metadata**
- Add `SCRAPER_SEARCH_QUERIES_JSON` parsing in `config.py`.
- Extend `Post` with `discovery_query`.

**Step 2: Add search ingestion to scraper**
- Request `/r/<subreddit>/search.json` for each configured query.
- Support both OAuth and public JSON paths.
- Merge search hits with feed hits and deduplicate by `post_id`.
- Preserve the first non-empty `discovery_query` for a post.

**Step 3: Surface metadata in report payload**
- Include `discovery_query` in the JSON report output so search-hit provenance is inspectable.

**Step 4: Re-run targeted scraper/config tests**

---

### Task 3: Implement optional DSPy Reddit parser and wire classifier fallback

**Objective:** Improve primary Reddit pain parsing quality while preserving the safe OpenRouter fallback path.

**Files:**
- Create: `dspy_parser.py`
- Modify: `classifier.py`
- Modify: `main.py`
- Modify: `requirements.txt`
- Modify: `README.md`
- Modify: `.env.example`

**Step 1: Implement DSPy wrapper**
- Lazy-import DSPy so the module does not break environments without the package.
- Build a `ChainOfThought` program for Reddit pain parsing.
- Map `DSPY_PROVIDER=codex` to an OpenAI-compatible DSPy LM configuration.
- Normalize DSPy outputs into `AnalysisResult`.

**Step 2: Wire classifier**
- Accept `dspy_parser` in `Classifier.__init__`.
- In `dual`/`b2b` mode, try DSPy first, then OpenRouter primary, then legacy fallback.

**Step 3: Wire composition root**
- Construct `DSPyRedditPainParser` in `main.py` only when enabled and credentials are present.
- Keep deep-dive / clustering / GTM on the current OpenRouter client.

**Step 4: Re-run targeted DSPy/classifier/main tests**

---

### Task 4: Validate, document, and prepare PR

**Objective:** Finish cleanly with repo policy compliance.

**Files:**
- Modify: `README.md`
- Modify: `.env.example`

**Step 1: Run required checks**
- `ruff check .`
- `pytest --cov=. --cov-fail-under=80 -q`
- `test -f .env || cp .env.example .env; docker compose config -q`

**Step 2: Review final diff**
- Verify no accidental `.venv/` or cache artifacts are staged.

**Step 3: Commit in logical steps and open draft PR**
- Use OpenClaw PR helper after checks pass.
