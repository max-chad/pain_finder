import logging
import math
import re
import sys
from typing import Any

import httpx

try:
    from sentence_transformers import SentenceTransformer  # type: ignore[import-untyped]
except Exception:  # ImportError or any init-time failure
    SentenceTransformer = None  # type: ignore[assignment,misc]

logger = logging.getLogger(__name__)

_DEFAULT_EMBED_BASE_URLS = {
    "openrouter": "https://openrouter.ai/api/v1/embeddings",
    "codex": "https://api.openai.com/v1/embeddings",
    "openai": "https://api.openai.com/v1/embeddings",
}
_EMBED_DIM = 96  # bag-of-words fallback dimension (matches clusterer.py)
_TOKEN_RE = re.compile(r"[a-z0-9_]{2,}")


def _embed_url_for_provider(provider: str, api_base: str) -> str:
    normalized = provider.strip().lower() or "openrouter"
    if api_base:
        return f"{api_base.rstrip('/')}/embeddings"
    return _DEFAULT_EMBED_BASE_URLS.get(normalized, _DEFAULT_EMBED_BASE_URLS["openai"])


async def _provider_embed_raw(
    *,
    api_key: str,
    model: str,
    text: str,
    provider: str,
    api_base: str = "",
) -> list[float]:
    """POST to the configured embeddings endpoint. Raises on non-200 or parse failure."""
    url = _embed_url_for_provider(provider, api_base)
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    if provider.strip().lower() == "openrouter":
        headers.update(
            {
                "HTTP-Referer": "https://github.com/max-chad/pain_finder",
                "X-Title": "pain_finder",
            }
        )

    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(
            url,
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


def cosine_similarity(left: list[float], right: list[float]) -> float:
    """Return cosine similarity for two vectors without raising.

    Candidate retrieval uses this as a bounded, deterministic fallback path in
    tests and when remote embedding providers are unavailable.  Dimension
    mismatches are treated as no semantic match instead of risking accidental
    promotion from malformed vectors.
    """
    if not left or not right or len(left) != len(right):
        return 0.0
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return sum(a * b for a, b in zip(left, right, strict=True)) / (left_norm * right_norm)


class Embedder:
    """Three-tier embedding with graceful fallback.

    Priority: configured API provider → sentence-transformers (local) → bag-of-words.
    embed() never raises; it always returns a list[float].
    """

    def __init__(self, *, api_key: str, model: str, provider: str = "openrouter", api_base: str = "") -> None:
        self._api_key = api_key
        self._model = model
        self._provider = provider.strip().lower() or "openrouter"
        self._api_base = api_base.strip()
        self._st_model: Any = None  # lazy-loaded SentenceTransformer instance

    async def embed(self, text: str) -> list[float]:
        """Return an embedding vector. Always succeeds."""
        if self._provider in {"bow", "hash", "disabled", "none"} or not self._api_key:
            return _bow_embed(text)

        try:
            return await _provider_embed_raw(
                api_key=self._api_key,
                model=self._model,
                text=text,
                provider=self._provider,
                api_base=self._api_base,
            )
        except Exception as exc:
            logger.warning("Provider embed failed (%s), trying sentence-transformers", exc)

        try:
            return self._st_embed(text)
        except Exception as exc:
            logger.warning("sentence-transformers embed failed (%s), using bag-of-words", exc)

        return _bow_embed(text)

    async def embed_many(self, texts: list[str]) -> list[list[float]]:
        """Embed a bounded batch sequentially through the same fail-soft path."""
        return [await self.embed(text) for text in texts]

    def _st_embed(self, text: str) -> list[float]:
        """Lazy-load SentenceTransformer and encode text. Raises if not installed."""
        if sys.modules.get("sentence_transformers") is None:
            raise ImportError("sentence-transformers is not installed")
        if SentenceTransformer is None:
            raise ImportError("sentence-transformers is not installed")
        if self._st_model is None:
            self._st_model = SentenceTransformer("all-MiniLM-L6-v2")
        return self._st_model.encode(text).tolist()
