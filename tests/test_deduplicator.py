import json
import math
from unittest.mock import AsyncMock, MagicMock, patch

import pytest_asyncio

from db import Database
from deduplicator import Deduplicator
from embedder import Embedder


def _make_vec(val: float, dim: int = 96) -> list[float]:
    """Return a unit-normalised vector where all values equal val/sqrt(dim)."""
    v = [val / math.sqrt(dim)] * dim
    return v


def _similar_vec(dim: int = 96) -> list[float]:
    """Two calls return identical vectors → cosine = 1.0 (above any threshold)."""
    return _make_vec(1.0, dim)


def _orthogonal_vec(dim: int = 96) -> list[float]:
    """Return a vector orthogonal to _similar_vec — cosine = 0."""
    v = [0.0] * dim
    v[0] = 1.0  # unit vector along first axis only
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


async def _insert(db, post_id, source="reddit", emb=None, *, title=None, body=None):
    await db.insert_pain_point(
        subreddit="test", post_id=post_id, url="", title=title or ("t " + post_id),
        body=body or ("b " + post_id), category="complaint", summary="s", severity="low",
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
        assert "hn_dup" in json.loads(canonical["cross_source_ids"])

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
        """DB read error → returns False (safe fallback, pipeline continues)."""
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
        shared_vec = _similar_vec()
        embedder.embed = AsyncMock(return_value=shared_vec)

        count = await dedup.backfill()

        assert count == 1
        reddit = await db.get_pain_point("reddit_post")
        hn = await db.get_pain_point("hn_post")
        statuses = {reddit["triage_status"], hn["triage_status"]}
        assert "merged" in statuses

    async def test_backfill_skips_embed_error(self, db):
        """Embed failure for one record doesn't crash backfill."""
        await _insert(db, "good", source="reddit")
        await _insert(db, "bad_embed", source="hn")

        dedup, embedder = _make_deduplicator(db)
        call_count = 0

        async def flaky_embed(text):
            nonlocal call_count
            call_count += 1
            if call_count == 2:
                raise RuntimeError("embed failed")
            return _similar_vec()

        embedder.embed = flaky_embed
        count = await dedup.backfill()  # must not raise
        assert count == 0  # only 1 of 2 embeddings stored, so no pair to merge

    async def test_backfill_logs_merge_failure_and_continues(self, db, caplog, monkeypatch):
        """A single merge failure should not stop later backfill merges."""
        await _insert(db, "reddit_a", source="reddit", title="Pair A reddit", body="shared")
        await _insert(db, "hn_a", source="hn", title="Pair A hn", body="shared")
        await _insert(db, "reddit_b", source="reddit", title="Pair B reddit", body="shared")
        await _insert(db, "hn_b", source="hn", title="Pair B hn", body="shared")

        dedup, embedder = _make_deduplicator(db)
        vec_a = [1.0] + [0.0] * 95
        vec_b = [0.0, 1.0] + [0.0] * 94

        async def embed_for_text(text: str) -> list[float]:
            if "pair a" in text.lower():
                return vec_a
            return vec_b

        embedder.embed = AsyncMock(side_effect=embed_for_text)

        original_merge_duplicate = db.merge_duplicate
        merge_calls = 0

        async def flaky_merge_duplicate(*, canonical_post_id, dup_post_id, dup_emb_vector):
            nonlocal merge_calls
            merge_calls += 1
            if merge_calls == 1:
                raise RuntimeError("merge failed")
            return await original_merge_duplicate(
                canonical_post_id=canonical_post_id,
                dup_post_id=dup_post_id,
                dup_emb_vector=dup_emb_vector,
            )

        monkeypatch.setattr(db, "merge_duplicate", flaky_merge_duplicate)

        with caplog.at_level("INFO"):
            count = await dedup.backfill()

        assert count == 1

        reddit_a = await db.get_pain_point("reddit_a")
        hn_a = await db.get_pain_point("hn_a")
        reddit_b = await db.get_pain_point("reddit_b")
        hn_b = await db.get_pain_point("hn_b")

        assert reddit_a is not None
        assert hn_a is not None
        assert reddit_b is not None
        assert hn_b is not None
        assert hn_a["triage_status"] != "merged"
        assert hn_b["triage_status"] == "merged"

        backfill_logs = [rec.message for rec in caplog.records if "dedup backfill complete" in rec.message]
        assert any("merge_failed_count=1" in message for message in backfill_logs)
