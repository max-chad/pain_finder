# Cross-Source Semantic Deduplication Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Detect when a newly ingested pain point is semantically equivalent to one from a different source, then merge it into the canonical record (incrementing `cross_source_count`) instead of inserting a duplicate row.

**Architecture:** New `Embedder` class owns a three-tier fallback chain (OpenRouter API → sentence-transformers → bag-of-words). New `Deduplicator` class owns similarity search and merge logic. A dedup check is inserted in `pipeline._analyze_posts()` before each DB insert. A one-time backfill runs at startup.

**Tech Stack:** httpx (already installed), sentence-transformers (new optional dep), aiosqlite, respx (test mocking, already installed)

---

## Task 1: DB Schema — 3 New Columns + "merged" Exclusions

**Files:**
- Modify: `db.py:10` (`PAIN_POINT_STATUSES`)
- Modify: `db.py:175-187` (`PAIN_POINT_COLUMNS`)
- Modify: `db.py:228-234` (`_run_migrations()`)
- Modify: `db.py:499-516` (`list_export_rows()`)
- Modify: `db.py:611-623` (`get_macro_candidates()`)
- Test: `tests/test_db.py`

**Step 1: Write the failing test for new column existence**

Add to `tests/test_db.py`:

```python
async def test_dedup_columns_exist(db):
    """New columns exist after init."""
    row = await db.get_pain_point("nonexistent")
    assert row is None  # DB initialised cleanly

    await db.insert_pain_point(
        subreddit="test", post_id="col_check", url="", title="t", body="b",
        category="complaint", summary="s", severity="low",
    )
    row = await db.get_pain_point("col_check")
    assert row is not None
    assert "emb_vector" in row
    assert "cross_source_count" in row
    assert "cross_source_ids" in row
    assert row["cross_source_count"] == 1
    assert row["cross_source_ids"] == "[]"
    assert row["emb_vector"] is None
```

**Step 2: Run test to verify it fails**

```
pytest tests/test_db.py::test_dedup_columns_exist -v
```
Expected: FAIL — `KeyError: 'emb_vector'`

**Step 3: Add columns to `PAIN_POINT_COLUMNS` dict (`db.py:175-187`)**

Add three new entries at the end of the `PAIN_POINT_COLUMNS` dict:

```python
PAIN_POINT_COLUMNS = {
    # ... existing entries unchanged ...
    "analysis_payload_json": "TEXT",
    # NEW:
    "emb_vector": "TEXT",
    "cross_source_count": "INTEGER DEFAULT 1",
    "cross_source_ids": "TEXT DEFAULT '[]'",
}
```

**Step 4: Add migration name (`db.py:228`)**

```python
migration_names = [
    "2026_02_24_expand_pain_points",
    "2026_02_25_phase_5_8_expansion",
    "2026_02_27_cross_source_dedup",   # NEW
]
```

**Step 5: Exclude merged records from exports and clustering**

In `list_export_rows()` (`db.py:500`), change the conditions list initializer:
```python
conditions = ["triage_status NOT IN ('discarded', 'merged')"]
```

In `get_macro_candidates()` (`db.py:614`), change the WHERE clause:
```python
WHERE datetime(created_at) >= datetime('now', ?)
  AND triage_status NOT IN ('discarded', 'merged')
  AND (triage_status = 'favorite' OR willingness_to_pay >= ?)
```

**Step 6: Run test to verify it passes**

```
pytest tests/test_db.py::test_dedup_columns_exist -v
```
Expected: PASS

**Step 7: Commit**

```bash
git add db.py tests/test_db.py
git commit -m "feat(db): add emb_vector/cross_source_count/cross_source_ids columns; exclude merged from exports"
```

---

## Task 2: DB Methods — `store_embedding`, `get_pain_points_with_embeddings`, `get_pain_points_without_embeddings`, `merge_duplicate`

**Files:**
- Modify: `db.py` (add 4 methods after `get_pain_point` at line 388)
- Test: `tests/test_db.py`

**Step 1: Write failing tests**

Add to `tests/test_db.py`:

```python
async def _insert_test_point(db, post_id, source="reddit"):
    """Helper to insert a minimal pain point."""
    await db.insert_pain_point(
        subreddit="test", post_id=post_id, url="", title="Test title",
        body="Test body", category="complaint", summary="s", severity="low",
        source=source,
    )


async def test_store_and_retrieve_embedding(db):
    await _insert_test_point(db, "emb1")
    vector = [0.1, 0.2, 0.3]
    await db.store_embedding("emb1", vector)
    rows = await db.get_pain_points_with_embeddings()
    assert len(rows) == 1
    assert rows[0]["post_id"] == "emb1"
    assert rows[0]["emb_vector"] == vector


async def test_get_pain_points_without_embeddings(db):
    await _insert_test_point(db, "no_emb1")
    await _insert_test_point(db, "no_emb2")
    await db.store_embedding("no_emb1", [0.5, 0.5])
    rows = await db.get_pain_points_without_embeddings()
    assert len(rows) == 1
    assert rows[0]["post_id"] == "no_emb2"
    assert "title" in rows[0]
    assert "body" in rows[0]


async def test_merge_duplicate_increments_count(db):
    await _insert_test_point(db, "canonical", source="reddit")
    await _insert_test_point(db, "dup1", source="hn")
    dup_vec = [0.9, 0.1]
    await db.merge_duplicate(
        canonical_post_id="canonical",
        dup_post_id="dup1",
        dup_emb_vector=dup_vec,
    )
    canonical = await db.get_pain_point("canonical")
    assert canonical["cross_source_count"] == 2
    assert "dup1" in canonical["cross_source_ids"]

    dup = await db.get_pain_point("dup1")
    assert dup["triage_status"] == "merged"
    import json
    stored_vec = json.loads(dup["emb_vector"])
    assert stored_vec == dup_vec
```

**Step 2: Run tests to verify they fail**

```
pytest tests/test_db.py::test_store_and_retrieve_embedding tests/test_db.py::test_get_pain_points_without_embeddings tests/test_db.py::test_merge_duplicate_increments_count -v
```
Expected: FAIL — `AttributeError: 'Database' object has no attribute 'store_embedding'`

**Step 3: Add `store_embedding` method**

Add after `get_pain_point()` in `db.py`:

```python
async def store_embedding(self, post_id: str, emb_vector: list[float]) -> None:
    await self._conn.execute(
        "UPDATE pain_points SET emb_vector = ? WHERE post_id = ?",
        (json.dumps(emb_vector), post_id),
    )
    await self._conn.commit()
```

**Step 4: Add `get_pain_points_with_embeddings` method**

```python
async def get_pain_points_with_embeddings(self) -> list[dict[str, Any]]:
    """Returns all rows that have a stored embedding (not merged duplicates)."""
    async with self._conn.execute(
        "SELECT post_id, source, emb_vector FROM pain_points "
        "WHERE emb_vector IS NOT NULL AND triage_status != 'merged'"
    ) as cursor:
        rows = await cursor.fetchall()
    result = []
    for row in rows:
        d = dict(row)
        d["emb_vector"] = json.loads(d["emb_vector"])
        result.append(d)
    return result
```

**Step 5: Add `get_pain_points_without_embeddings` method**

```python
async def get_pain_points_without_embeddings(self) -> list[dict[str, Any]]:
    """Returns all rows missing an embedding (used for backfill)."""
    async with self._conn.execute(
        "SELECT post_id, source, title, body FROM pain_points "
        "WHERE emb_vector IS NULL AND triage_status != 'merged'"
    ) as cursor:
        rows = await cursor.fetchall()
    return [dict(row) for row in rows]
```

**Step 6: Add `merge_duplicate` method**

```python
async def merge_duplicate(
    self,
    *,
    canonical_post_id: str,
    dup_post_id: str,
    dup_emb_vector: list[float],
) -> None:
    """Merge a duplicate into the canonical record.

    Increments cross_source_count and appends dup_post_id to cross_source_ids
    on the canonical.  Marks the duplicate row as merged and stores its embedding.
    """
    # Fetch current cross_source_ids from canonical
    async with self._conn.execute(
        "SELECT cross_source_ids FROM pain_points WHERE post_id = ?",
        (canonical_post_id,),
    ) as cursor:
        row = await cursor.fetchone()
    if row is None:
        logger.warning("merge_duplicate: canonical %s not found", canonical_post_id)
        return

    current_ids: list[str] = json.loads(row["cross_source_ids"] or "[]")
    if dup_post_id not in current_ids:
        current_ids.append(dup_post_id)

    await self._conn.execute(
        "UPDATE pain_points SET cross_source_count = cross_source_count + 1, "
        "cross_source_ids = ? WHERE post_id = ?",
        (json.dumps(current_ids), canonical_post_id),
    )
    await self._conn.execute(
        "UPDATE pain_points SET emb_vector = ?, triage_status = 'merged' WHERE post_id = ?",
        (json.dumps(dup_emb_vector), dup_post_id),
    )
    await self._conn.commit()
    logger.info("merge_duplicate: merged %s -> canonical %s", dup_post_id, canonical_post_id)
```

**Step 7: Also update `insert_pain_point` to accept `emb_vector`**

Add the optional kwarg to the signature and store it. In `db.py:308`, after `analysis_payload`:

```python
        analysis_payload: dict[str, Any] | None = None,
        emb_vector: list[float] | None = None,   # NEW
```

In the INSERT statement (`db.py:320-325`), add `emb_vector` to the column list and values:

```python
                INSERT INTO pain_points (
                    subreddit, post_id, url, title, body, category, summary, severity,
                    is_monetizable, pain_level, willingness_to_pay, niche_category,
                    competitor_tags, source, triage_status, analysis_mode,
                    deep_dive_status, deep_dive_summary, analysis_payload_json,
                    emb_vector
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
```

Add `json.dumps(emb_vector) if emb_vector is not None else None` as the last value in the tuple (`db.py:368`).

In the `ON CONFLICT DO UPDATE SET` block, do NOT include `emb_vector` — keep the existing embedding if re-ingesting the same post_id.

**Step 8: Run tests to verify they pass**

```
pytest tests/test_db.py -v
```
Expected: ALL PASS

**Step 9: Commit**

```bash
git add db.py tests/test_db.py
git commit -m "feat(db): add store_embedding, get_pain_points_with/without_embeddings, merge_duplicate, update insert_pain_point"
```

---

## Task 3: New `embedder.py` — Three-Tier Fallback Chain

**Files:**
- Create: `embedder.py`
- Create: `tests/test_embedder.py`
- Modify: `requirements.txt` (add sentence-transformers)

**Step 1: Add sentence-transformers to requirements.txt**

Add at the end:
```
sentence-transformers>=3.0
```

Install it:
```
pip install sentence-transformers>=3.0
```

**Step 2: Write failing tests**

Create `tests/test_embedder.py`:

```python
import json
import math
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import respx
import httpx

from embedder import Embedder


def _make_embedder():
    return Embedder(api_key="test_key", model="google/text-embedding-004")


def _unit_vector(dim: int) -> list[float]:
    """Return a simple L2-normalised vector for testing."""
    v = [1.0 / math.sqrt(dim)] * dim
    return v


class TestOpenRouterEmbed:
    @respx.mock
    async def test_openrouter_success_returns_embedding(self):
        embedding = _unit_vector(384)
        respx.post("https://openrouter.ai/api/v1/embeddings").mock(
            return_value=httpx.Response(
                200,
                json={"data": [{"embedding": embedding}]},
            )
        )
        e = _make_embedder()
        result = await e.embed("test text")
        assert result == embedding

    @respx.mock
    async def test_fallback_to_st_on_http_error(self):
        """When OpenRouter returns 500, falls back to sentence-transformers."""
        respx.post("https://openrouter.ai/api/v1/embeddings").mock(
            return_value=httpx.Response(500, json={"error": "internal"})
        )
        fake_st_vec = _unit_vector(384)
        mock_model = MagicMock()
        mock_model.encode.return_value = MagicMock(tolist=lambda: fake_st_vec)

        with patch("embedder.SentenceTransformer", return_value=mock_model):
            e = _make_embedder()
            result = await e.embed("test text")

        assert result == fake_st_vec

    async def test_fallback_to_bow_when_st_not_installed(self):
        """Falls back to bag-of-words when sentence-transformers is unavailable."""
        import sys
        with (
            patch("embedder._openrouter_embed_raw", side_effect=Exception("network")),
            patch.dict(sys.modules, {"sentence_transformers": None}),
        ):
            e = _make_embedder()
            result = await e.embed("hello world hello")

        assert isinstance(result, list)
        assert len(result) == 96
        # L2-normalised — magnitude should be ≈ 1
        magnitude = math.sqrt(sum(x * x for x in result))
        assert abs(magnitude - 1.0) < 1e-6

    @respx.mock
    async def test_embed_never_raises(self):
        """embed() must not propagate any exception."""
        respx.post("https://openrouter.ai/api/v1/embeddings").mock(
            return_value=httpx.Response(500, json={})
        )
        import sys
        with patch.dict(sys.modules, {"sentence_transformers": None}):
            e = _make_embedder()
            # Should return bow vector without raising
            result = await e.embed("some text")
        assert isinstance(result, list)
```

**Step 3: Run tests to verify they fail**

```
pytest tests/test_embedder.py -v
```
Expected: FAIL — `ModuleNotFoundError: No module named 'embedder'`

**Step 4: Create `embedder.py`**

```python
import json
import logging
import math
import re
from typing import Any

import httpx

logger = logging.getLogger(__name__)

_EMBED_URL = "https://openrouter.ai/api/v1/embeddings"
_EMBED_DIM = 96  # bag-of-words fallback dimension (matches clusterer.py)
_TOKEN_RE = re.compile(r"[a-z0-9_]{2,}")


async def _openrouter_embed_raw(*, api_key: str, model: str, text: str) -> list[float]:
    """POST to OpenRouter embeddings endpoint. Raises on non-200 or parse failure."""
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(
            _EMBED_URL,
            headers=headers,
            json={"model": model, "input": text},
        )
        response.raise_for_status()
    return response.json()["data"][0]["embedding"]


def _bow_embed(text: str) -> list[float]:
    """96-dim L2-normalised hash-based bag-of-words. Never raises."""
    vector = [0.0] * _EMBED_DIM
    for token in _TOKEN_RE.findall(text.lower()):
        vector[hash(token) % _EMBED_DIM] += 1.0
    norm = math.sqrt(sum(v * v for v in vector))
    if norm == 0:
        return vector
    return [v / norm for v in vector]


class Embedder:
    """Three-tier embedding with graceful fallback.

    Priority: OpenRouter API → sentence-transformers (local) → bag-of-words.
    embed() never raises; it always returns a list[float].
    """

    def __init__(self, *, api_key: str, model: str) -> None:
        self._api_key = api_key
        self._model = model
        self._st_model: Any = None  # lazy-loaded SentenceTransformer instance

    async def embed(self, text: str) -> list[float]:
        """Return an embedding vector. Always succeeds."""
        try:
            return await _openrouter_embed_raw(
                api_key=self._api_key, model=self._model, text=text
            )
        except Exception as exc:
            logger.warning("OpenRouter embed failed (%s), trying sentence-transformers", exc)

        try:
            return self._st_embed(text)
        except Exception as exc:
            logger.warning("sentence-transformers embed failed (%s), using bag-of-words", exc)

        return _bow_embed(text)

    def _st_embed(self, text: str) -> list[float]:
        """Lazy-load SentenceTransformer and encode text. Raises ImportError if not installed."""
        from sentence_transformers import SentenceTransformer  # type: ignore[import-untyped]

        if self._st_model is None:
            self._st_model = SentenceTransformer("all-MiniLM-L6-v2")
        return self._st_model.encode(text).tolist()
```

**Step 5: Run tests to verify they pass**

```
pytest tests/test_embedder.py -v
```
Expected: ALL PASS

**Step 6: Commit**

```bash
git add embedder.py tests/test_embedder.py requirements.txt
git commit -m "feat: add Embedder with OpenRouter/sentence-transformers/bow fallback chain"
```

---

## Task 4: New `deduplicator.py` — Similarity Search + Merge + Backfill

**Files:**
- Create: `deduplicator.py`
- Create: `tests/test_deduplicator.py`

**Step 1: Write failing tests**

Create `tests/test_deduplicator.py`:

```python
import math
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio

from db import Database
from deduplicator import Deduplicator
from embedder import Embedder


def _make_vec(val: float, dim: int = 96) -> list[float]:
    """Return a unit-normalised vector where all values equal val/sqrt(dim)."""
    v = [val / math.sqrt(dim)] * dim
    return v


def _similar_vec(dim: int = 96) -> list[float]:
    """Return a vector that's ≥0.88 cosine-similar to _make_vec(1.0)."""
    # Cosine of two unit vectors with identical values = 1.0
    return _make_vec(1.0, dim)


def _orthogonal_vec(dim: int = 96) -> list[float]:
    """Return a vector orthogonal to _make_vec — cosine = 0."""
    v = [0.0] * dim
    v[0] = 1.0  # unit vector along first axis
    return v


@pytest_asyncio.fixture
async def db(tmp_path):
    database = Database(str(tmp_path / "dedup_test.db"))
    await database.init()
    yield database
    await database.close()


def _make_deduplicator(db, threshold=0.88):
    embedder = MagicMock(spec=Embedder)
    return Deduplicator(db=db, embedder=embedder, threshold=threshold), embedder


async def _insert(db, post_id, source="reddit", emb=None):
    await db.insert_pain_point(
        subreddit="test", post_id=post_id, url="", title="t " + post_id,
        body="b " + post_id, category="complaint", summary="s", severity="low",
        source=source, emb_vector=emb,
    )


class TestFindAndMerge:
    async def test_cross_source_dup_detected_and_merged(self, db):
        """Two embeddings above threshold from different sources → merges."""
        canonical_vec = _similar_vec()
        await _insert(db, "canonical", source="reddit", emb=canonical_vec)

        dedup, _ = _make_deduplicator(db)
        new_vec = _similar_vec()  # cosine = 1.0 with canonical
        is_dup = await dedup.find_and_merge(
            post_id="hn_dup", embedding=new_vec, source="hn"
        )

        assert is_dup is True
        canonical = await db.get_pain_point("canonical")
        assert canonical["cross_source_count"] == 2
        assert "hn_dup" in canonical["cross_source_ids"]

    async def test_same_source_not_merged(self, db):
        """Same source → never a dup, even if vectors are identical."""
        canonical_vec = _similar_vec()
        await _insert(db, "canonical", source="reddit", emb=canonical_vec)

        dedup, _ = _make_deduplicator(db)
        is_dup = await dedup.find_and_merge(
            post_id="reddit2", embedding=_similar_vec(), source="reddit"
        )

        assert is_dup is False

    async def test_below_threshold_not_merged(self, db):
        """Cosine below threshold → not a dup."""
        await _insert(db, "canonical", source="reddit", emb=_similar_vec())

        dedup, _ = _make_deduplicator(db)
        is_dup = await dedup.find_and_merge(
            post_id="hn_diff", embedding=_orthogonal_vec(), source="hn"
        )

        assert is_dup is False

    async def test_db_error_returns_false(self, db):
        """DB read error → returns False (safe fallback)."""
        dedup, _ = _make_deduplicator(db)
        with patch.object(db, "get_pain_points_with_embeddings", side_effect=Exception("DB down")):
            result = await dedup.find_and_merge(
                post_id="new_post", embedding=_similar_vec(), source="hn"
            )
        assert result is False


class TestBackfill:
    async def test_backfill_embeds_and_merges_known_pair(self, db):
        """Two records without embeddings from different sources get merged."""
        await _insert(db, "reddit_post", source="reddit")
        await _insert(db, "hn_post", source="hn")

        dedup, embedder = _make_deduplicator(db)
        # Both embed to the same vector → will be merged
        shared_vec = _similar_vec()
        embedder.embed = AsyncMock(return_value=shared_vec)

        count = await dedup.backfill()

        assert count == 1
        # One of the two is now merged; the canonical has cross_source_count=2
        reddit = await db.get_pain_point("reddit_post")
        hn = await db.get_pain_point("hn_post")
        statuses = {reddit["triage_status"], hn["triage_status"]}
        assert "merged" in statuses

    async def test_backfill_skips_embed_error(self, db):
        """Embed failure for one record doesn't crash backfill."""
        await _insert(db, "good", source="reddit")
        await _insert(db, "bad", source="hn")

        dedup, embedder = _make_deduplicator(db)
        call_count = 0

        async def flaky_embed(text):
            nonlocal call_count
            call_count += 1
            if call_count == 2:
                raise RuntimeError("embed failed")
            return _similar_vec()

        embedder.embed = flaky_embed
        count = await dedup.backfill()  # Should not raise
        assert count == 0  # no pair could be formed
```

**Step 2: Run tests to verify they fail**

```
pytest tests/test_deduplicator.py -v
```
Expected: FAIL — `ModuleNotFoundError: No module named 'deduplicator'`

**Step 3: Create `deduplicator.py`**

```python
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from db import Database
    from embedder import Embedder

logger = logging.getLogger(__name__)


def _cosine(a: list[float], b: list[float]) -> float:
    """Cosine similarity between two equal-length L2-normalised vectors."""
    if len(a) != len(b):
        return 0.0
    return sum(x * y for x, y in zip(a, b))


class Deduplicator:
    """Cross-source semantic deduplication.

    On each new post: look up stored embeddings, find the best cross-source
    match above *threshold*, and merge if found.  Returns True when the new
    post is a duplicate (caller should skip inserting it).

    backfill() processes all existing records that have no stored embedding,
    embeds them, and merges any cross-source pairs found.
    """

    def __init__(
        self,
        *,
        db: "Database",
        embedder: "Embedder",
        threshold: float = 0.88,
    ) -> None:
        self._db = db
        self.embedder = embedder
        self._threshold = threshold
        self._cache: list[dict] | None = None  # reset after backfill

    async def find_and_merge(
        self, *, post_id: str, embedding: list[float], source: str
    ) -> bool:
        """Check for a cross-source semantic duplicate and merge if found.

        Returns True when *post_id* is a duplicate (do not insert it).
        Returns False on any error so the caller proceeds with a safe insert.
        """
        try:
            stored = await self._get_cache()
        except Exception as exc:
            logger.warning("dedup: DB read failed (%s), skipping dedup check", exc)
            return False

        best_score = 0.0
        best_match: dict | None = None

        for record in stored:
            if record["source"] == source:
                continue  # only cross-source matches
            score = _cosine(embedding, record["emb_vector"])
            if score > best_score:
                best_score = score
                best_match = record

        if best_match is not None and best_score >= self._threshold:
            try:
                await self._db.merge_duplicate(
                    canonical_post_id=best_match["post_id"],
                    dup_post_id=post_id,
                    dup_emb_vector=embedding,
                )
                logger.info(
                    "dedup: merged %s (source=%s) -> canonical=%s (score=%.3f)",
                    post_id,
                    source,
                    best_match["post_id"],
                    best_score,
                )
                # Refresh cache so subsequent posts in the same run see updated state
                self._cache = None
            except Exception as exc:
                logger.warning("dedup: merge_duplicate failed (%s), skipping", exc)
                return False
            return True

        # Not a dup: add to cache so the next post in this run can match against it
        if self._cache is not None:
            self._cache.append({
                "post_id": post_id,
                "source": source,
                "emb_vector": embedding,
            })
        return False

    async def backfill(self) -> int:
        """Embed all records without a vector and merge cross-source pairs.

        Safe to run multiple times — already-embedded records are skipped.
        Returns the number of pairs merged.
        """
        self._cache = None  # start fresh

        # Phase 1: embed records that have no vector yet
        to_embed = await self._db.get_pain_points_without_embeddings()
        logger.info("dedup backfill: %d records to embed", len(to_embed))

        for record in to_embed:
            try:
                text = f"{record['title']} {record['body']}"
                vec = await self.embedder.embed(text)
                await self._db.store_embedding(record["post_id"], vec)
            except Exception as exc:
                logger.warning(
                    "dedup backfill: embed failed for %s (%s), skipping",
                    record["post_id"],
                    exc,
                )

        # Phase 2: pairwise merge pass over all stored embeddings
        all_stored = await self._db.get_pain_points_with_embeddings()
        logger.info("dedup backfill: %d stored embeddings, running pairwise pass", len(all_stored))

        merged_count = 0
        merged_ids: set[str] = set()

        for i, a in enumerate(all_stored):
            if a["post_id"] in merged_ids:
                continue
            for b in all_stored[i + 1:]:
                if b["post_id"] in merged_ids:
                    continue
                if a["source"] == b["source"]:
                    continue
                score = _cosine(a["emb_vector"], b["emb_vector"])
                if score >= self._threshold:
                    try:
                        await self._db.merge_duplicate(
                            canonical_post_id=a["post_id"],
                            dup_post_id=b["post_id"],
                            dup_emb_vector=b["emb_vector"],
                        )
                        merged_ids.add(b["post_id"])
                        merged_count += 1
                        logger.info(
                            "dedup backfill: merged %s -> %s (score=%.3f)",
                            b["post_id"],
                            a["post_id"],
                            score,
                        )
                    except Exception as exc:
                        logger.warning("dedup backfill: merge failed (%s)", exc)

        logger.info("dedup backfill complete: %d pairs merged", merged_count)
        self._cache = None  # force reload on next find_and_merge
        return merged_count

    async def _get_cache(self) -> list[dict]:
        if self._cache is None:
            self._cache = await self._db.get_pain_points_with_embeddings()
        return self._cache
```

**Step 4: Run tests to verify they pass**

```
pytest tests/test_deduplicator.py -v
```
Expected: ALL PASS

**Step 5: Commit**

```bash
git add deduplicator.py tests/test_deduplicator.py
git commit -m "feat: add Deduplicator with cross-source similarity search, merge, and backfill"
```

---

## Task 5: `config.py` — Two New Constants

**Files:**
- Modify: `config.py` (add 2 lines after line 20)
- Test: (no dedicated test needed; conftest sentinel values cover import)

**Step 1: Add constants to `config.py` after line 20**

```python
EMBED_MODEL = os.getenv("EMBED_MODEL", "google/text-embedding-004")
DEDUP_SIMILARITY_THRESHOLD = float(os.getenv("DEDUP_SIMILARITY_THRESHOLD", "0.88"))
```

**Step 2: Verify config imports cleanly**

```
python -c "import config; print(config.EMBED_MODEL, config.DEDUP_SIMILARITY_THRESHOLD)"
```
Expected output: `google/text-embedding-004 0.88`

**Step 3: Commit**

```bash
git add config.py
git commit -m "feat(config): add EMBED_MODEL and DEDUP_SIMILARITY_THRESHOLD env vars"
```

---

## Task 6: `pipeline.py` — Dedup Check Before Insert

**Files:**
- Modify: `pipeline.py:44-61` (`__init__`)
- Modify: `pipeline.py:104-122` (`_analyze_posts` loop)
- Test: `tests/test_pipeline.py`

**Step 1: Write the failing test**

Add to `tests/test_pipeline.py`:

```python
async def test_cross_source_dedup_skips_second_insert(db, tmp_path):
    """When deduplicator marks a signal as a dup, DB insert is skipped."""
    from unittest.mock import patch
    from deduplicator import Deduplicator
    from embedder import Embedder

    post_reddit = Post(
        post_id="r_post1", subreddit="test", title="Stripe webhooks unreliable",
        body="They keep failing randomly", url="https://reddit.com/r_post1", score=5,
    )
    post_hn = Post(
        post_id="hn_post1", subreddit="hackernews", title="Stripe reliability is terrible",
        body="Webhooks drop all the time", url="https://news.ycombinator.com/hn_post1", score=3,
    )
    signal_reddit = PainSignal(
        post=post_reddit, category="complaint", summary="Stripe webhook failures",
        severity="high", is_monetizable=True, pain_level=7, willingness_to_pay=7,
        niche_category="Payments", analysis_mode="b2b",
    )
    signal_hn = PainSignal(
        post=post_hn, category="complaint", summary="Stripe webhook failures",
        severity="high", is_monetizable=True, pain_level=7, willingness_to_pay=7,
        niche_category="Payments", analysis_mode="b2b",
    )

    scraper = AsyncMock()
    scraper.fetch_posts.return_value = [post_reddit, post_hn]
    scraper.fetch_full_thread.return_value = []
    classifier = SimpleNamespace(
        classify_batch=AsyncMock(return_value=[signal_reddit, signal_hn]),
        openrouter=None,
    )

    # Embedder always returns same vector; deduplicator will mark hn_post1 as dup
    shared_vec = [1.0 / (96 ** 0.5)] * 96
    embedder = AsyncMock(spec=Embedder)
    embedder.embed = AsyncMock(return_value=shared_vec)

    deduplicator = Deduplicator(db=db, embedder=embedder, threshold=0.88)

    pipeline = AnalysisPipeline(
        scraper=scraper,
        classifier=classifier,
        db=db,
        reports_dir=str(tmp_path / "reports"),
        deep_dive_wtp_threshold=99,  # disable deep dive
        deduplicator=deduplicator,
    )

    run = await pipeline.analyze_subreddit("test", limit=2)

    # Only one record should be in DB (the duplicate was merged, not inserted)
    rows = await db.get_pain_points(subreddit="test")
    # reddit post is canonical; hn is merged into it
    assert len(rows) == 1
    assert rows[0]["post_id"] == "r_post1"
    assert rows[0]["cross_source_count"] == 2
```

**Step 2: Run test to verify it fails**

```
pytest tests/test_pipeline.py::test_cross_source_dedup_skips_second_insert -v
```
Expected: FAIL — `TypeError: __init__() got an unexpected keyword argument 'deduplicator'`

**Step 3: Update `AnalysisPipeline.__init__` signature (`pipeline.py:44-60`)**

Add `deduplicator` kwarg:

```python
from deduplicator import Deduplicator   # add to imports at top

class AnalysisPipeline:
    def __init__(
        self,
        scraper: RedditScraper,
        classifier: Classifier,
        db: Database,
        reports_dir: str,
        deep_dive_wtp_threshold: int = 8,
        deep_dive_max_comments: int = 250,
        budget_guard: BudgetGuard | None = None,
        deduplicator: Deduplicator | None = None,   # NEW
    ):
        # ... existing assignments ...
        self.deduplicator = deduplicator            # NEW
```

**Step 4: Update `_analyze_posts` loop (`pipeline.py:104-122`)**

Replace the existing `for signal in signals:` block (lines 104-122) with:

```python
        for signal in signals:
            embedding: list[float] | None = None

            if self.deduplicator is not None:
                text = f"{signal.post.title} {signal.post.body}"
                embedding = await self.deduplicator.embedder.embed(text)
                is_dup = await self.deduplicator.find_and_merge(
                    post_id=signal.post.post_id,
                    embedding=embedding,
                    source=source,
                )
                if is_dup:
                    continue  # duplicate merged into canonical; skip insert

            await self.db.insert_pain_point(
                subreddit=signal.post.subreddit,
                post_id=signal.post.post_id,
                url=signal.post.url,
                title=signal.post.title,
                body=signal.post.body,
                category=signal.category,
                summary=signal.summary,
                severity=signal.severity,
                is_monetizable=signal.is_monetizable,
                pain_level=signal.pain_level,
                willingness_to_pay=signal.willingness_to_pay,
                niche_category=signal.niche_category,
                competitor_tags=signal.competitor_tags,
                source=source,
                analysis_mode=signal.analysis_mode,
                analysis_payload=signal.analysis_payload,
                emb_vector=embedding,   # NEW
            )

            if signal.is_monetizable:
                monetizable_count += 1

            if signal.is_monetizable and signal.willingness_to_pay >= self.deep_dive_wtp_threshold:
                # ... deep dive logic unchanged ...
```

Note: the `monetizable_count` / deep dive block must remain AFTER the `await self.db.insert_pain_point(...)` call. Do not change that ordering.

**Step 5: Run test to verify it passes**

```
pytest tests/test_pipeline.py -v
```
Expected: ALL PASS

**Step 6: Commit**

```bash
git add pipeline.py tests/test_pipeline.py
git commit -m "feat(pipeline): add dedup check before insert in _analyze_posts"
```

---

## Task 7: `main.py` — Wire Embedder + Deduplicator + Backfill

**Files:**
- Modify: `main.py:1-18` (imports)
- Modify: `main.py:41-73` (`run()` function)

**Step 1: Add imports at top of `main.py`**

After the existing import block (line 17 or so), add:

```python
from deduplicator import Deduplicator
from embedder import Embedder
```

**Step 2: Instantiate Embedder and Deduplicator after `openrouter` (`main.py:55-73`)**

After the `openrouter = OpenRouterClient(...)` block (line ~63), add:

```python
    embedder = Embedder(
        api_key=config.OPENROUTER_API_KEY,
        model=config.EMBED_MODEL,
    )
    deduplicator = Deduplicator(
        db=db,
        embedder=embedder,
        threshold=config.DEDUP_SIMILARITY_THRESHOLD,
    )
```

**Step 3: Pass `deduplicator` to `AnalysisPipeline` (`main.py:65-73`)**

```python
    pipeline = AnalysisPipeline(
        scraper=scraper,
        classifier=classifier,
        db=db,
        reports_dir=config.REPORTS_DIR,
        deep_dive_wtp_threshold=config.DEEP_DIVE_WTP_THRESHOLD,
        deep_dive_max_comments=config.DEEP_DIVE_MAX_COMMENTS,
        budget_guard=budget_guard,
        deduplicator=deduplicator,   # NEW
    )
```

**Step 4: Run backfill after `db.init()` (`main.py:43`)**

After `await db.init()` and before `budget_guard = BudgetGuard(...)`, add:

```python
    dedup_merged = await deduplicator.backfill()
    logger.info("Dedup backfill complete: %d cross-source duplicates merged", dedup_merged)
```

Wait — `deduplicator` is defined later. Move the `Embedder` + `Deduplicator` instantiation to immediately after `await db.init()` and before `budget_guard`. Then call backfill. The revised startup order:

```python
async def run() -> None:
    db = Database(config.DB_PATH)
    await db.init()

    # Wire deduplication services early so backfill runs before scheduler starts
    embedder = Embedder(api_key=config.OPENROUTER_API_KEY, model=config.EMBED_MODEL)
    deduplicator = Deduplicator(db=db, embedder=embedder, threshold=config.DEDUP_SIMILARITY_THRESHOLD)
    dedup_merged = await deduplicator.backfill()
    logger.info("Dedup backfill complete: %d cross-source duplicates merged", dedup_merged)

    budget_guard = BudgetGuard(db=db, daily_cap_usd=config.DAILY_BUDGET_USD)
    # ... rest of run() unchanged ...
```

**Step 5: Verify `main.py` imports cleanly (dry-run)**

```
python -c "import main"
```
Expected: no errors

**Step 6: Commit**

```bash
git add main.py
git commit -m "feat(main): wire Embedder + Deduplicator, run backfill at startup"
```

---

## Task 8: Quality Gates + mypy

**Step 1: Run ruff**

```
ruff check .
```
Expected: no errors. Fix any that appear (most will be unused imports or line-length).

**Step 2: Run mypy**

```
mypy .
```

Likely issues and fixes:
- `sentence_transformers` has no stubs → already handled with `# type: ignore[import-untyped]` in `embedder.py`
- `list[dict] | None` annotation on `_cache` needs `from __future__ import annotations` or use `Optional` — add `from __future__ import annotations` at top of `deduplicator.py`

Fix any mypy errors before moving on.

**Step 3: Run full test suite**

```
pytest --cov=. --cov-fail-under=80 -q
```
Expected: all pass, coverage ≥ 80%.

**Step 4: Commit if any lint fixes were needed**

```bash
git add -u
git commit -m "fix: address ruff/mypy issues in embedder and deduplicator"
```

---

## Verification

### Manual smoke test (requires real env vars)

```bash
# 1. Set in .env:
#    EMBED_MODEL=google/text-embedding-004
#    DEDUP_SIMILARITY_THRESHOLD=0.88

# 2. Run once to trigger backfill
python main.py
# Check logs for: "Dedup backfill complete: N cross-source duplicates merged"

# 3. After ingestion from two sources, query for merged records:
python -c "
import asyncio, json
from db import Database
import config

async def check():
    db = Database(config.DB_PATH)
    await db.init()
    import aiosqlite
    async with db._conn.execute(
        'SELECT post_id, source, cross_source_count, cross_source_ids '
        'FROM pain_points WHERE cross_source_count > 1'
    ) as cur:
        rows = await cur.fetchall()
    for r in rows:
        print(dict(r))
    await db.close()

asyncio.run(check())
"
```

### Unit test suite

```bash
pytest tests/test_db.py tests/test_embedder.py tests/test_deduplicator.py tests/test_pipeline.py -v
```

---

## Summary of Files Changed

| File | Change |
|------|--------|
| `db.py` | +3 columns, +4 methods, update `insert_pain_point`, update `list_export_rows`/`get_macro_candidates` |
| `pipeline.py` | `deduplicator` param + dedup check in loop |
| `config.py` | +2 env vars |
| `main.py` | Import + instantiate + backfill |
| `requirements.txt` | +sentence-transformers |
| `embedder.py` | **NEW** |
| `deduplicator.py` | **NEW** |
| `tests/test_embedder.py` | **NEW** |
| `tests/test_deduplicator.py` | **NEW** |
| `tests/test_db.py` | +4 test functions |
| `tests/test_pipeline.py` | +1 test function |
