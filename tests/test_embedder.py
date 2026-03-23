import math
from unittest.mock import MagicMock, patch

import httpx
import respx

from embedder import Embedder


def _make_embedder():
    return Embedder(api_key="test_key", model="google/text-embedding-004")


def _unit_vector(dim: int) -> list[float]:
    """Return a simple L2-normalised vector for testing."""
    return [1.0 / math.sqrt(dim)] * dim


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

        import sys
        with (
            patch.dict(sys.modules, {"sentence_transformers": MagicMock()}),
            patch("embedder.SentenceTransformer", return_value=mock_model),
        ):
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
            result = await e.embed("some text")
        assert isinstance(result, list)
