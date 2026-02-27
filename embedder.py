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
        """Lazy-load SentenceTransformer and encode text. Raises if not installed."""
        # Check sys.modules at call-time so that tests can disable the dependency
        # by setting sys.modules["sentence_transformers"] = None.
        if sys.modules.get("sentence_transformers") is None:
            raise ImportError("sentence-transformers is not installed")
        # Use the module-level SentenceTransformer name so tests can patch it via
        # patch("embedder.SentenceTransformer", ...).
        if SentenceTransformer is None:
            raise ImportError("sentence-transformers is not installed")
        if self._st_model is None:
            self._st_model = SentenceTransformer("all-MiniLM-L6-v2")
        return self._st_model.encode(text).tolist()
