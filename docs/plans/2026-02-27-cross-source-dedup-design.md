# Cross-Source Semantic Deduplication — Design Doc

**Date:** 2026-02-27
**Status:** Approved

## Problem

pain_finder ingests B2B pain points from multiple sources (Reddit, HN, review sites). Because `post_id` is the only unique key, the same underlying complaint described differently across sources creates separate records. This inflates clustering noise and obscures true signal strength — a pain that surfaces on three platforms should register as a stronger signal, not three independent weak ones.

## Goal

When a newly ingested pain point is semantically similar to an existing one from a *different* source, merge it into the canonical record (increment `cross_source_count`, append to `cross_source_ids`) rather than storing a separate row. Run a one-time backfill to deduplicate existing historical records.

## Non-Goals

- Same-source deduplication (not in scope)
- Exact-text deduplication only (semantic similarity is required)
- Real-time dedup UI in Telegram (out of scope for this iteration)

## Approach

**Approach A — New `embedder.py` + `deduplicator.py` services** (chosen)

Clean separation of concerns. The embedder owns the fallback chain; the deduplicator owns similarity search and merge logic. Easy to test each layer independently.

Rejected alternatives:
- Extend `clusterer.py` — blurs macro-trend clustering vs. dedup responsibility
- Two-pass SHA-256 + semantic — premature optimization for current insert volumes

## Architecture

```
embedder.py         — Fallback embedding chain
deduplicator.py     — Similarity search + merge-on-match + backfill
db.py               — 3 additive columns + 4 new methods
pipeline.py         — Dedup check before insert
config.py           — 2 new env vars
main.py             — Wire services + call backfill at startup
```

### Embedding Fallback Chain

`Embedder.embed(text: str) -> list[float]` — never raises, always returns a vector:

1. **OpenRouter embeddings API** (`POST /api/v1/embeddings`, model `EMBED_MODEL`, default `google/text-embedding-004`). Same API key as existing chat completions.
2. **sentence-transformers** (`all-MiniLM-L6-v2`, lazy-loaded, cached on instance). Falls back if OpenRouter returns non-200 or raises.
3. **Bag-of-words** (copy of `Clusterer._embed()`, 96-dim L2-normalized). Falls back if sentence-transformers not installed or fails. Pure Python, always succeeds.

### Deduplication Logic

`Deduplicator.find_and_merge(post_id, embedding, source) -> bool`:

1. Load all stored embeddings from DB (cached in `self._cache` per run).
2. For each record where `record.source != source` (cross-source only): compute cosine similarity.
3. If best match ≥ `DEDUP_SIMILARITY_THRESHOLD` (default `0.88`): call `db.merge_duplicate()`, return `True`.
4. Otherwise: add to cache, return `False`.

Threshold of `0.88` is above the macro-clustering threshold (`0.72`) to minimize false positives.

### Merge Semantics

`db.merge_duplicate(canonical_post_id, dup_post_id, dup_emb_vector)`:

- Increments `cross_source_count` on canonical
- Appends `dup_post_id` to `cross_source_ids` JSON array on canonical
- Stores embedding on duplicate row (so backfill skips it)
- Sets `triage_status = 'merged'` on duplicate

The duplicate row is retained but flagged. The canonical row is the authoritative record.

### DB Schema Changes (additive only)

| Column | Type | Default | Purpose |
|--------|------|---------|---------|
| `emb_vector` | `TEXT` | `NULL` | JSON-encoded `list[float]` |
| `cross_source_count` | `INTEGER` | `1` | Number of sources reporting this pain |
| `cross_source_ids` | `TEXT` | `'[]'` | JSON array of merged duplicate `post_id`s |

### Backfill (one-time, startup)

`Deduplicator.backfill() -> int`:

1. Fetch all records without `emb_vector`.
2. Embed each (`title + " " + body`), store via `db.store_embedding()`.
3. Reload all embeddings, run pairwise cosine pass (skip `triage_status='merged'` records).
4. Merge all cross-source pairs above threshold.
5. Return merge count.

Subsequent startups skip records already having `emb_vector`.

### Pipeline Integration

In `pipeline._analyze_posts()`, before each `db.insert_pain_point()`:

```python
embedding = await self.deduplicator.embedder.embed(text)
is_dup = await self.deduplicator.find_and_merge(post_id, embedding, source)
if is_dup:
    continue
await self.db.insert_pain_point(..., emb_vector=embedding)
```

## Error Handling

- `find_and_merge()` catches all DB errors → logs + returns `False` (safe insert proceeds)
- `backfill()` catches per-record embed errors → logs + skips record
- `embed()` never raises — bow fallback is pure Python with no failure mode

## New Config Variables

| Var | Default | Purpose |
|-----|---------|---------|
| `EMBED_MODEL` | `google/text-embedding-004` | OpenRouter embedding model |
| `DEDUP_SIMILARITY_THRESHOLD` | `0.88` | Cosine threshold for merge |

## Testing

| File | Coverage |
|------|---------|
| `tests/test_embedder.py` | OpenRouter success; fallback to ST on HTTP error; fallback to BoW when ST missing; never raises |
| `tests/test_deduplicator.py` | Cross-source dup detected; same-source not merged; below threshold skipped; backfill merges pair; DB error → False |
| `tests/test_pipeline.py` | Two signals (reddit + HN), high overlap → insert called once |
| `tests/test_db.py` | `merge_duplicate` increments count; `store_embedding` round-trips |

## Reused Utilities

- `Clusterer._embed()` (`clusterer.py:220`) — copied into `embedder.py._bow_embed()`
- `Clusterer._cosine()` (`clusterer.py:269`) — copied into `deduplicator.py._cosine()`
- httpx pattern from `openrouter.py` — reference for `_openrouter_embed()`
