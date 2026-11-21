import asyncio
from collections.abc import Sequence

import numpy as np
from google import genai
from google.genai import errors as genai_errors
from google.genai import types
from tenacity import (
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential_jitter,
)

from app.core.config import Settings
from app.core.logging import get_logger

logger = get_logger(__name__)

_DEFAULT_BATCH_SIZE = 50


def _l2_normalize(vector: Sequence[float]) -> list[float]:
    arr = np.asarray(vector, dtype=np.float32)
    norm = float(np.linalg.norm(arr))
    if norm > 0.0:
        arr = arr / norm
    return arr.tolist()


def _is_retryable_gemini_error(exc: BaseException) -> bool:
    if isinstance(exc, genai_errors.APIError):
        return exc.code in {429, 500, 502, 503, 504}
    return isinstance(exc, (TimeoutError, ConnectionError))


class GeminiEmbeddingAdapter:
    """
    Free-tier Google Gemini embedding adapter (`gemini-embedding-001`).

    Uses Matryoshka truncation (`output_dimensionality=768`) with mandatory L2
    normalization and asymmetric task types (`RETRIEVAL_DOCUMENT` / `RETRIEVAL_QUERY`).
    """

    def __init__(
        self,
        *,
        api_key: str,
        model_name: str = "gemini-embedding-001",
        dimensions: int = 768,
        batch_size: int = _DEFAULT_BATCH_SIZE,
    ) -> None:
        if not api_key:
            raise ValueError(
                "GEMINI_API_KEY is required when EMBEDDING_PROVIDER='gemini'."
            )
        self._client = genai.Client(api_key=api_key)
        self._model_name = model_name
        self._dimensions = dimensions
        self._batch_size = max(1, min(batch_size, 100))

    @property
    def model_name(self) -> str:
        return self._model_name

    @property
    def dimensions(self) -> int:
        return self._dimensions

    @retry(
        retry=retry_if_exception(_is_retryable_gemini_error),
        wait=wait_exponential_jitter(initial=0.5, max=8.0),
        stop=stop_after_attempt(4),
        reraise=True,
    )
    def _embed_batch_sync(
        self, texts: list[str], task_type: str
    ) -> list[list[float]]:
        response = self._client.models.embed_content(
            model=self._model_name,
            contents=texts,  # type: ignore[arg-type]
            config=types.EmbedContentConfig(
                output_dimensionality=self._dimensions,
                task_type=task_type,
            ),
        )
        embeddings = response.embeddings or []
        if len(embeddings) != len(texts):
            raise RuntimeError(
                f"Expected {len(texts)} embeddings from {self._model_name}, "
                f"received {len(embeddings)}."
            )
        normalized: list[list[float]] = []
        for emb in embeddings:
            values = emb.values
            if not values or len(values) != self._dimensions:
                raise RuntimeError(
                    f"Unexpected embedding dimension: expected {self._dimensions}, "
                    f"got {len(values) if values else 0}."
                )
            normalized.append(_l2_normalize(values))
        return normalized

    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        if not texts:
            return []
        text_list = list(texts)
        results: list[list[float]] = []
        for start in range(0, len(text_list), self._batch_size):
            batch = text_list[start : start + self._batch_size]
            batch_vectors = await asyncio.to_thread(
                self._embed_batch_sync, batch, "RETRIEVAL_DOCUMENT"
            )
            results.extend(batch_vectors)
        logger.info(
            "gemini_embed_documents_complete",
            model=self._model_name,
            count=len(results),
            dim=self._dimensions,
        )
        return results

    async def embed_query(self, text: str) -> list[float]:
        vectors = await asyncio.to_thread(
            self._embed_batch_sync, [text], "RETRIEVAL_QUERY"
        )
        return vectors[0]


class FastEmbedEmbeddingAdapter:
    """Optional offline ONNX embedding adapter (e.g. `nomic-ai/nomic-embed-text-v1.5`, 768d)."""

    def __init__(
        self,
        *,
        model_name: str = "nomic-ai/nomic-embed-text-v1.5",
        dimensions: int = 768,
    ) -> None:
        from fastembed import TextEmbedding

        self._model_name = model_name
        self._dimensions = dimensions
        self._encoder = TextEmbedding(model_name=model_name)

    @property
    def model_name(self) -> str:
        return self._model_name

    @property
    def dimensions(self) -> int:
        return self._dimensions

    def _encode_sync(self, texts: list[str]) -> list[list[float]]:
        vectors = [_l2_normalize(v.tolist()) for v in self._encoder.embed(texts)]
        if vectors and len(vectors[0]) != self._dimensions:
            raise RuntimeError(
                f"FastEmbed model '{self._model_name}' emitted dim {len(vectors[0])}, "
                f"but EMBEDDING_DIM is configured to {self._dimensions}."
            )
        return vectors

    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        if not texts:
            return []
        prefixed = [f"search_document: {t}" for t in texts]
        return await asyncio.to_thread(self._encode_sync, prefixed)

    async def embed_query(self, text: str) -> list[float]:
        vectors = await asyncio.to_thread(self._encode_sync, [f"search_query: {text}"])
        return vectors[0]


def create_embedding_adapter(
    settings: Settings,
) -> GeminiEmbeddingAdapter | FastEmbedEmbeddingAdapter:
    if settings.embedding_provider == "fastembed":
        model = (
            settings.embedding_model
            if "/" in settings.embedding_model
            else "nomic-ai/nomic-embed-text-v1.5"
        )
        return FastEmbedEmbeddingAdapter(
            model_name=model,
            dimensions=settings.embedding_dim,
        )
    return GeminiEmbeddingAdapter(
        api_key=settings.gemini_api_key,
        model_name=settings.embedding_model,
        dimensions=settings.embedding_dim,
    )
