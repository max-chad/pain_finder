# Codex Reserve Routing Implementation Plan

> **For Hermes:** Use the `complex-dev-preflight` skill before implementation, then execute with TDD and small commits.

**Goal:** Make `pain_finder` call the ChatGPT Codex backend in the same way Hermes does, so requests route through the intended Codex quota/account path instead of the generic/main ChatGPT path.

**Architecture:** Keep the current `openai-codex` provider path in `pain_finder`, but align its request construction with Hermes' own Codex integration. Specifically: add the Codex-specific headers (`originator`, `User-Agent`, `ChatGPT-Account-ID`) to Responses API calls, derive the account id from the OAuth JWT, and expose enough observability in tests/docs to prevent regressions.

**Research findings (pre-implementation):**
- Official Hermes docs: credential pools are same-provider rotation; fallback providers are only used after the whole pool is exhausted.
- Official Hermes docs: multiple `openai-codex` OAuth credentials can be added via `hermes auth add openai-codex --type oauth --label <name>`.
- Current local auth state has only **one** `openai-codex` credential in the pool, so there is no separate reserve credential to select today.
- `pain_finder` currently bypasses Hermes' Codex header parity: `openrouter.py` creates `OpenAI(api_key, base_url)` without the Codex-specific default headers.
- Hermes' own implementation (`agent/auxiliary_client.py::_codex_cloudflare_headers`) explicitly sets:
  - `User-Agent: codex_cli_rs/...`
  - `originator: codex_cli_rs`
  - `ChatGPT-Account-ID` derived from the JWT claim `https://api.openai.com/auth.chatgpt_account_id`
- That header set is documented in Hermes source as required for ChatGPT Codex backend routing / Cloudflare compatibility.

**Non-goal for this slice:** Build full dynamic runtime refresh/selection from Hermes auth pool inside the container. That is a larger follow-up and only matters if/when a second Codex credential is actually present.

---

## Task 1: Lock in the routing regression with tests

**Objective:** Add failing tests that prove the current `openai-codex` path does not send Codex-specific headers.

**Files:**
- Modify: `tests/test_openrouter.py`

**Step 1: Add a unit test for Codex header derivation**
- Assert that the helper extracts `ChatGPT-Account-ID` from a JWT-shaped token.
- Assert that it always includes `originator=codex_cli_rs` and the Codex CLI-style `User-Agent`.

**Step 2: Extend the existing streamed Responses test**
- Capture `OpenAI(...)` constructor kwargs.
- Assert `default_headers` is present and contains the Codex-specific headers.

**Step 3: Run targeted tests**
```bash
pytest tests/test_openrouter.py::test_openai_codex_provider_parses_streamed_json_and_tracks_usage -q
pytest tests/test_openrouter.py::test_codex_header_builder_extracts_account_id_from_jwt -q
```
Expected: fail before implementation.

---

## Task 2: Implement Codex header parity in `openrouter.py`

**Objective:** Mirror Hermes' Codex backend headers in `pain_finder`.

**Files:**
- Modify: `openrouter.py`

**Step 1: Add a helper that builds Codex backend headers**
- Derive `ChatGPT-Account-ID` from the JWT payload when possible.
- Return a safe header set even when the token is malformed.

**Step 2: Use those headers in the Responses API client**
- Pass `default_headers=...` into `OpenAI(...)` for the `openai-codex` path.

**Step 3: Keep non-Codex providers unchanged**
- No behavior change for `openrouter`, `openai`, or `codex` API-key providers.

**Step 4: Re-run targeted tests**
```bash
pytest tests/test_openrouter.py -q
```
Expected: pass.

---

## Task 3: Document the real constraint around “reserve” selection

**Objective:** Record what is and is not possible with the current auth state.

**Files:**
- Modify: `README.md`

**Step 1: Document Codex backend parity requirement**
- Mention that ChatGPT Codex backend requests need Codex CLI-like headers.

**Step 2: Document reserve-credential prerequisite**
- State that selecting a true reserve credential requires adding a second `openai-codex` OAuth credential to Hermes' credential pool.

---

## Task 4: Validate end-to-end and report the blocker clearly

**Objective:** Verify code quality and runtime viability, then summarize the operational blocker if the reserve credential still doesn't exist.

**Files:**
- No new code files required

**Step 1: Run repo checks**
```bash
ruff check .
pytest --cov=. --cov-fail-under=80 -q
docker compose config -q
```

**Step 2: Inspect Hermes auth pool**
```bash
hermes auth list openai-codex
```

**Step 3: Report outcome**
- If pool still has only one credential: say the routing bug is fixed, but true reserve selection remains blocked until a second labeled credential exists.
- If a reserve credential appears: do the next slice to select it explicitly.

---

## Follow-up Plan (only if user wants true reserve selection)
1. Add a host-side sync helper that resolves a specific labeled Codex credential from Hermes auth.
2. Refresh/write that credential into `pain_finder/.env` before deploy.
3. Optionally add a timer to resync before token expiry.
4. Only after a second credential exists, add explicit label-based reserve selection.
