import hashlib
import json
import logging
import math
import re
from collections import Counter
from dataclasses import dataclass, field
from statistics import mean, median
from typing import Any

from budget import BudgetCapReachedError
from db import Database
from openrouter import MacroClusterLabel, OpenRouterClient

logger = logging.getLogger(__name__)

TOKEN_RE = re.compile(r"[a-z0-9_]{2,}")

# EMBED_DIM controls the length of the hash-based bag-of-words vector used for
# cosine-similarity clustering.  The value 96 is intentionally small: it keeps
# memory usage low and removes the need for any external ML dependency (no
# numpy, scikit-learn, or sentence-transformers).
#
# Trade-off / known limitation
# ----------------------------
# With only 96 buckets and typical pain-point summaries of 20-50 tokens, the
# probability of two *different* tokens mapping to the same bucket is high
# (birthday-paradox effect).  These hash collisions inflate the dot-product
# between unrelated posts and can cause them to be merged into the same cluster
# even though their actual content is dissimilar.  In other words, cosine
# similarity scores computed from this embedding are an approximation, not a
# ground-truth measure of semantic similarity.
#
# If clustering accuracy matters more than keeping the codebase dependency-free,
# replace _embed() with a proper embedding model (e.g. sentence-transformers or
# an OpenRouter embeddings endpoint) and raise EMBED_DIM to match its output
# dimensionality.
#
# PYTHONHASHSEED note
# -------------------
# Python randomises hash() output for strings once per process start (controlled
# by the PYTHONHASHSEED environment variable).  This means the same token maps
# to a different EMBED_DIM bucket across process restarts, so cosine-similarity
# scores — and therefore the cluster assignments produced by _cluster_indices —
# are non-reproducible between runs.  Set PYTHONHASHSEED=0 to disable this
# randomisation and obtain deterministic results.  For the current use case
# (ephemeral, per-run macro-trend snapshots) non-reproducibility is acceptable,
# but it is worth knowing when debugging unexpected cluster differences.
EMBED_DIM = 96
STOPWORDS = {
    "about",
    "after",
    "again",
    "because",
    "before",
    "between",
    "breaks",
    "daily",
    "every",
    "from",
    "have",
    "keeps",
    "manual",
    "need",
    "still",
    "team",
    "teams",
    "their",
    "this",
    "with",
    "your",
}


@dataclass
class MacroTrendCluster:
    cluster_id: int
    label: str
    summary: str
    estimated_monetization_signal: str
    item_count: int
    aggregate_wtp: float
    post_ids: list[str]
    canonical_key: str = ""
    fresh_post_count: int = 0
    evergreen_post_count: int = 0
    median_buyer_authority: float = 0.0
    incumbents: list[str] = field(default_factory=list)
    avg_opportunity_score: float = 0.0
    pain_mentions_per_1000_posts: float = 0.0
    pain_mentions_per_1000_comments: float = 0.0
    unique_authors_count: int = 0
    unique_threads_count: int = 0
    weekly_delta: int = 0
    source_activity_baseline: dict[str, Any] = field(default_factory=dict)
    latest_source_created_ts: int | None = None


@dataclass
class MacroTrendRunResult:
    run_id: int
    window_days: int
    candidate_count: int
    clusters: list[MacroTrendCluster]


class MacroTrendClusterer:
    def __init__(
        self,
        db: Database,
        openrouter: OpenRouterClient | None,
        *,
        min_cluster_size: int = 3,
        similarity_threshold: float = 0.72,
        min_wtp: int = 8,
    ):
        self.db = db
        self.openrouter = openrouter
        self.min_cluster_size = max(2, min_cluster_size)
        self.similarity_threshold = max(0.1, min(1.0, similarity_threshold))
        self.min_wtp = max(0, min_wtp)

    async def run(self, window_days: int) -> MacroTrendRunResult:
        window_days = max(1, window_days)
        candidates = await self.db.get_macro_candidates(window_days=window_days, min_wtp=self.min_wtp)

        if not candidates:
            run_id = await self.db.create_macro_trend_run(
                window_days=window_days,
                candidate_count=0,
                cluster_count=0,
            )
            return MacroTrendRunResult(run_id=run_id, window_days=window_days, candidate_count=0, clusters=[])

        texts = [self._compose_candidate_text(row) for row in candidates]
        vectors = [self._embed(text) for text in texts]
        grouped_indices = self._cluster_indices(vectors)
        grouped_indices = [cluster for cluster in grouped_indices if len(cluster) >= self.min_cluster_size]

        run_id = await self.db.create_macro_trend_run(
            window_days=window_days,
            candidate_count=len(candidates),
            cluster_count=len(grouped_indices),
        )

        persisted_clusters: list[MacroTrendCluster] = []
        for cluster_indices in grouped_indices:
            members = [candidates[index] for index in cluster_indices]
            sample_lines = [self._compose_cluster_line(row) for row in members[:12]]
            cluster_text = "\n".join(sample_lines)
            aggregate_wtp = sum(float(row.get("willingness_to_pay") or 0) for row in members)
            fresh_post_count = sum(1 for row in members if str(row.get("opportunity_bucket") or "").strip().lower() == "current_opportunity")
            evergreen_post_count = sum(1 for row in members if str(row.get("opportunity_bucket") or "").strip().lower() == "evergreen_pain")
            authority_values = [float(row.get("buyer_authority_score") or 0.0) for row in members]
            median_buyer_authority = round(float(median(authority_values)), 3) if authority_values else 0.0
            incumbents = self._aggregate_incumbents(members)
            opportunity_scores = [float(row.get("opportunity_score") or 0.0) for row in members]
            avg_opportunity_score = round(float(mean(opportunity_scores)), 2) if opportunity_scores else 0.0
            latest_source_created_ts = max(int(row.get("source_created_ts") or 0) for row in members) or None
            source_counts = Counter(str(row.get("source") or "reddit").strip() or "reddit" for row in members)
            scope_counts = Counter(str(row.get("subreddit") or "").strip() for row in members)
            frequency_source = source_counts.most_common(1)[0][0] if source_counts else "reddit"
            frequency_scope = scope_counts.most_common(1)[0][0] if scope_counts else ""
            frequency_metrics = await self.db.calculate_normalized_frequency(
                source=frequency_source,
                scope=frequency_scope,
                post_ids=[str(row.get("post_id")) for row in members if row.get("post_id")],
            )
            label = await self._label_cluster(
                cluster_text=cluster_text,
                cluster_size=len(members),
                aggregate_wtp=aggregate_wtp,
            )
            canonical_key = self._canonical_key(members, label=label)
            resolved_label = label.label if label.label != "Trend Detected" else self._humanize_canonical_key(canonical_key)
            resolved_summary = (
                label.summary
                if label.label != "Trend Detected"
                else self._fallback_cluster_summary(
                    members=members,
                    fresh_post_count=fresh_post_count,
                    evergreen_post_count=evergreen_post_count,
                    incumbents=incumbents,
                )
            )

            member_rows = []
            for index in cluster_indices:
                row = candidates[index]
                similarity = self._cluster_member_similarity(vectors[index], [vectors[i] for i in cluster_indices])
                member_rows.append((str(row["post_id"]), similarity))

            cluster_id = await self.db.save_macro_cluster(
                run_id=run_id,
                canonical_key=canonical_key,
                cluster_key=str(members[0]["post_id"]),
                label=resolved_label,
                summary=resolved_summary,
                estimated_monetization_signal=label.estimated_monetization_signal,
                item_count=len(members),
                aggregate_wtp=aggregate_wtp,
                fresh_post_count=fresh_post_count,
                evergreen_post_count=evergreen_post_count,
                median_buyer_authority=median_buyer_authority,
                incumbents=incumbents,
                avg_opportunity_score=avg_opportunity_score,
                pain_mentions_per_1000_posts=frequency_metrics["pain_mentions_per_1000_posts"],
                pain_mentions_per_1000_comments=frequency_metrics["pain_mentions_per_1000_comments"],
                unique_authors_count=frequency_metrics["unique_authors_count"],
                unique_threads_count=frequency_metrics["unique_threads_count"],
                weekly_delta=frequency_metrics["weekly_delta"],
                source_activity_baseline=frequency_metrics["source_activity_baseline"],
                latest_source_created_ts=latest_source_created_ts,
                members=member_rows,
            )
            persisted_clusters.append(
                MacroTrendCluster(
                    cluster_id=cluster_id,
                    label=resolved_label,
                    summary=resolved_summary,
                    estimated_monetization_signal=label.estimated_monetization_signal,
                    item_count=len(members),
                    aggregate_wtp=aggregate_wtp,
                    post_ids=[str(member["post_id"]) for member in members],
                    canonical_key=canonical_key,
                    fresh_post_count=fresh_post_count,
                    evergreen_post_count=evergreen_post_count,
                    median_buyer_authority=median_buyer_authority,
                    incumbents=incumbents,
                    avg_opportunity_score=avg_opportunity_score,
                    pain_mentions_per_1000_posts=frequency_metrics["pain_mentions_per_1000_posts"],
                    pain_mentions_per_1000_comments=frequency_metrics["pain_mentions_per_1000_comments"],
                    unique_authors_count=frequency_metrics["unique_authors_count"],
                    unique_threads_count=frequency_metrics["unique_threads_count"],
                    weekly_delta=frequency_metrics["weekly_delta"],
                    source_activity_baseline=frequency_metrics["source_activity_baseline"],
                    latest_source_created_ts=latest_source_created_ts,
                )
            )

        persisted_clusters.sort(
            key=lambda cluster: (
                cluster.avg_opportunity_score,
                cluster.latest_source_created_ts or 0,
                cluster.item_count,
                cluster.aggregate_wtp,
            ),
            reverse=True,
        )
        logger.info(
            "macro_trend_complete stage=clustering run_id=%s window_days=%d candidates=%d clusters=%d",
            run_id,
            window_days,
            len(candidates),
            len(persisted_clusters),
        )
        return MacroTrendRunResult(
            run_id=run_id,
            window_days=window_days,
            candidate_count=len(candidates),
            clusters=persisted_clusters,
        )

    async def _label_cluster(
        self,
        *,
        cluster_text: str,
        cluster_size: int,
        aggregate_wtp: float,
    ) -> MacroClusterLabel:
        if self.openrouter is not None:
            try:
                labeled = await self.openrouter.label_macro_cluster(
                    cluster_text=cluster_text,
                    cluster_size=cluster_size,
                )
                if labeled is not None:
                    return labeled
            except BudgetCapReachedError:
                raise
            except Exception as e:
                logger.warning("Cluster labeling failed, falling back: %s", e)

        signal = "high" if aggregate_wtp >= cluster_size * 7 else "medium" if aggregate_wtp >= cluster_size * 4 else "low"
        return MacroClusterLabel(
            label="Trend Detected",
            summary=f"{cluster_size} related complaints were grouped from recent high-signal pain points.",
            estimated_monetization_signal=signal,
            key_complaints=[],
        )

    @staticmethod
    def _compose_candidate_text(row: dict[str, Any]) -> str:
        competitor_tags = row.get("competitor_tags")
        if isinstance(competitor_tags, str):
            try:
                parsed = json.loads(competitor_tags)
                if isinstance(parsed, list):
                    competitor_tags = parsed
            except json.JSONDecodeError:
                competitor_tags = []
        if not isinstance(competitor_tags, list):
            competitor_tags = []
        tags = ", ".join(str(tag) for tag in competitor_tags[:8])
        return " | ".join(
            [
                str(row.get("title") or ""),
                str(row.get("summary") or ""),
                str(row.get("deep_dive_summary") or ""),
                tags,
            ]
        ).strip()

    @staticmethod
    def _compose_cluster_line(row: dict[str, Any]) -> str:
        return (
            f"- post={row.get('post_id')} "
            f"wtp={row.get('willingness_to_pay', 0)} "
            f"summary={str(row.get('summary') or '')[:180]}"
        )

    @staticmethod
    def _parse_tags(raw: Any) -> list[str]:
        if isinstance(raw, list):
            return [str(item).strip().lower() for item in raw if str(item).strip()]
        if isinstance(raw, str) and raw.strip():
            try:
                parsed = json.loads(raw)
            except json.JSONDecodeError:
                return []
            if isinstance(parsed, list):
                return [str(item).strip().lower() for item in parsed if str(item).strip()]
        return []

    @classmethod
    def _aggregate_incumbents(cls, members: list[dict[str, Any]]) -> list[str]:
        counts: Counter[str] = Counter()
        for row in members:
            counts.update(cls._parse_tags(row.get("competitor_tags")))
        return [tag for tag, _ in sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:5]]

    @classmethod
    def _canonical_key(cls, members: list[dict[str, Any]], label: MacroClusterLabel | None = None) -> str:
        counts: Counter[str] = Counter()
        if label is not None and label.label.strip().lower() != "trend detected":
            for phrase in [label.label, *label.key_complaints]:
                for token in TOKEN_RE.findall(str(phrase).lower()):
                    if len(token) < 4 or token in STOPWORDS:
                        continue
                    counts[token] += 3
        normalized_fragments: list[str] = []
        for row in members:
            text = " ".join(
                str(part or "")
                for part in [row.get("title"), row.get("summary"), row.get("deep_dive_summary")]
            )
            normalized_fragments.append(text.lower().strip())
            for token in TOKEN_RE.findall(text.lower()):
                if len(token) < 4 or token in STOPWORDS:
                    continue
                counts[token] += 1
        parts: list[str] = []
        for token, _ in sorted(counts.items(), key=lambda item: (-item[1], item[0])):
            if token in parts:
                continue
            parts.append(token)
            if len(parts) >= 4:
                break
        if parts:
            return "-".join(parts)[:96].strip("-")
        fingerprint = hashlib.sha1("|".join(sorted(fragment for fragment in normalized_fragments if fragment)).encode("utf-8")).hexdigest()[:10]
        return f"cluster-{fingerprint}"

    @staticmethod
    def _humanize_canonical_key(canonical_key: str) -> str:
        if canonical_key.startswith("cluster-"):
            return "Recurring pain cluster"
        words = [segment for segment in canonical_key.replace("_", "-").split("-") if segment]
        if not words:
            return "Recurring pain cluster"
        return " ".join(word.capitalize() for word in words[:6])

    @staticmethod
    def _fallback_cluster_summary(
        *,
        members: list[dict[str, Any]],
        fresh_post_count: int,
        evergreen_post_count: int,
        incumbents: list[str],
    ) -> str:
        incumbent_text = ", ".join(incumbents[:3]) or "none"
        return (
            f"{len(members)} related pain posts grouped into one recurring problem. "
            f"Fresh={fresh_post_count}, evergreen={evergreen_post_count}, incumbents={incumbent_text}."
        )

    @staticmethod
    def _embed(text: str) -> list[float]:
        # Hash-based bag-of-words embedding: each token is hashed into one of
        # EMBED_DIM buckets and its count is accumulated there.  The resulting
        # vector is then L2-normalised so that _cosine() returns cosine
        # similarity directly.
        #
        # Because EMBED_DIM is small (96), multiple distinct tokens collide into
        # the same bucket.  This can make two semantically unrelated posts look
        # similar after normalisation.  See the comment on EMBED_DIM above for
        # the full trade-off discussion.
        vector = [0.0 for _ in range(EMBED_DIM)]
        for token in TOKEN_RE.findall(text.lower()):
            index = hash(token) % EMBED_DIM
            vector[index] += 1.0
        norm = math.sqrt(sum(value * value for value in vector))
        if norm == 0:
            return vector
        return [value / norm for value in vector]

    def _cluster_indices(self, vectors: list[list[float]]) -> list[list[int]]:
        assigned = [False] * len(vectors)
        clusters: list[list[int]] = []

        for i in range(len(vectors)):
            if assigned[i]:
                continue
            cluster = [i]
            assigned[i] = True
            changed = True
            while changed:
                changed = False
                for j in range(len(vectors)):
                    if assigned[j]:
                        continue
                    if any(self._cosine(vectors[j], vectors[k]) >= self.similarity_threshold for k in cluster):
                        cluster.append(j)
                        assigned[j] = True
                        changed = True
            clusters.append(cluster)
        return clusters

    @staticmethod
    def _cluster_member_similarity(vector: list[float], cluster_vectors: list[list[float]]) -> float:
        if not cluster_vectors:
            return 0.0
        score = sum(MacroTrendClusterer._cosine(vector, other) for other in cluster_vectors) / len(cluster_vectors)
        return round(score, 4)

    @staticmethod
    def _cosine(a: list[float], b: list[float]) -> float:
        if len(a) != len(b):
            return 0.0
        return sum(x * y for x, y in zip(a, b))
