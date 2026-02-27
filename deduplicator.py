from __future__ import annotations

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
        db: Database,
        embedder: Embedder,
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
                self._cache = None  # refresh so subsequent posts see updated state
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
        logger.info(
            "dedup backfill: %d stored embeddings, running pairwise pass",
            len(all_stored),
        )

        merged_count = 0
        merged_ids: set[str] = set()

        for i, a in enumerate(all_stored):
            if a["post_id"] in merged_ids:
                continue
            for b in all_stored[i + 1 :]:
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
