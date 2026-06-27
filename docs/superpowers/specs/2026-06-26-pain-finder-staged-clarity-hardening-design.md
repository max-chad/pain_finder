# Pain Finder Staged Clarity Hardening Design

Date: 2026-06-26

## Context

`main` is green and canonical. The repo is not in rescue-from-red mode. This pass is about consolidation, clarity, and hardening: align the product story with the code that already exists, then close the highest-value control-plane gaps without pretending the system needs a full rewrite.

## Recommended Framing

`pain_finder` should be framed as an operator-controlled, evidence-backed B2B opportunity intelligence pipeline.

- Telegram is the control plane.
- Posts are evidence, not the product.
- Clusters and opportunity candidates are the primary product unit.
- Reports, exports, GTM payloads, and digests are secondary views over that decision object.

This framing is a better fit than parser-centric language because the repo already does more than parse posts. It verifies evidence, tracks hard negatives, clusters signals, generates GTM context, and supports operator feedback.

## Problem Map

### 1. Product Narrative Drift

The README and eval docs still lean toward "parser" language. That under-specifies:

- the primary decision surface;
- the role of clusters versus individual posts;
- the meaning of evidence, hard negatives, and promotion eligibility;
- what the eval harness is actually measuring.

### 2. Control-Plane Trust Gaps

The runtime has a few high-value failure modes that need clearer hardening:

- budget guard overshoot under concurrent LLM classification because admission is check-then-act and accounting is post-call;
- accounting failures are fail-open and mostly logged instead of escalating the current operation;
- `openai-codex` routing can degrade silently when the account claim is missing or malformed;
- healthcheck does not yet verify `llm_usage_events` or runtime-row integrity deeply enough;
- dedup embed failures can abort a valid run instead of degrading to best-effort behavior;
- review-target validation currently happens too late in startup order.

### 3. Readiness And DevEx Drift

The docs and CI story are not aligned:

- README quickstart does not make the required env bootstrap obvious, even though `config.py` fails fast at import time;
- an existing plan doc still points to dead `healthcheck.py --strict` guidance instead of `--fail-on-job-errors`;
- CI is green without exercising readiness commands such as `healthcheck.py` and `smoke_collect.py`.

## Goals

- Reframe the repo around evidence-backed B2B opportunity intelligence.
- Keep Telegram as the operator control plane and clusters as the primary product unit.
- Make readiness and runtime failures visible early instead of silently degraded.
- Keep the current green baseline intact while hardening the trust boundaries.
- Expand evals so they measure product-level decisions, not parser vibes alone.

## Non-Goals

- Do not treat this as a production rescue from a red branch.
- Do not rewrite the whole architecture.
- Do not bulk-merge stale side branches without dispositioning them by invariant.
- Do not replace Telegram with a new UI.
- Do not claim deployment readiness without explicit readiness checks and operator review.
- Do not add new production dependencies or paid services as part of the framing pass.

## Phased Roadmap

### Phase 1: Clarify The Product Story

- Update top-level docs so the first-order framing is "operator-controlled, evidence-backed B2B opportunity intelligence pipeline."
- Define the key nouns once: evidence, hard negative, cluster, opportunity candidate, promotion eligible, decision surface.
- Reword eval docs so the harness is clearly a starter scorecard for product-level decisions, not just a parser benchmark.

### Phase 2: Make Readiness First-Class

- Document the required env bootstrap explicitly.
- Align README, healthcheck, smoke-check docs, and CI command names.
- Make the readiness story distinguish Docker liveness from operator readiness gating.

### Phase 3: Close Fail-Open Runtime Paths

- Validate review targets before expensive startup work.
- Keep dedup embed failures and merge failures from aborting otherwise-valid runs.
- Escalate accounting failures instead of treating them as harmless warnings.

### Phase 4: Harden Budget And Accounting

- Make budget/accounting failure modes explicit and observable.
- Check runtime rows and usage-event integrity in healthcheck.
- Fix `openai-codex` routing so malformed or missing account claims fail closed rather than silently degrading.
- Treat concurrency overshoot as a structural issue, not a quick patch.

### Phase 5: Expand Product-Level Evals

- Grow the labeled set toward a product-level benchmark, not a parser-only toy set.
- Add hard negatives, evidence-grounding cases, current-opportunity cases, and cluster-usefulness checks.
- Make eval outputs speak to operator decisions: what to keep, what to discard, and what to research next.

## Decision Rationale

The repo already has enough functionality to support the stronger framing. What it lacks is coherence: the docs still talk like a parser project, while the runtime is already an evidence-backed opportunity pipeline with operator controls. The fastest high-leverage work is therefore not new features. It is clarity, readiness, and hardening around the control plane and budget/accounting edges.

The roadmap intentionally separates quick, low-risk trust fixes from structural budget rework. That keeps the pass honest: the repo can become more legible and more reliable without pretending a concurrency-safe spend redesign is a same-day patch.

## Success Definition

This design is done when the docs, readiness commands, and eval language all point to the same product:

- Telegram is the control plane.
- Clusters and opportunity candidates are the decision unit.
- Evidence and hard negatives are first-class concepts.
- Readiness commands are documented and exercised.
- Budget/accounting failures are visible.
- Evals measure product decisions, not just parser output.
