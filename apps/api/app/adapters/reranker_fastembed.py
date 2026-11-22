import asyncio
import math
import re
from collections.abc import Sequence
from typing import Any

from app.core.logging import get_logger
from app.domain.models import RerankedChunk, RetrievedChunk

logger = get_logger(__name__)

# Matches structured technical codes like ERR_SIG_4092, ERR_GLOBEX_9901, RB-WH-204, HTTP_429
_EXACT_CODE_RE = re.compile(r"\b[A-Z]{2,}[_-][A-Z0-9_-]*\d+[A-Z0-9_-]*\b")
_EXACT_CODE_FLOOR_SCORE = 0.78


def sigmoid(logit: float) -> float:
    """Numerically stable sigmoid mapping unbounded cross-encoder logits into (0, 1)."""
    if logit >= 0.0:
        z = math.exp(-logit)
        return 1.0 / (1.0 + z)
    z = math.exp(logit)
    return z / (1.0 + z)


def extract_exact_code_identifiers(query: str) -> list[str]:
    """Extract uppercase alphanumeric error/runbook codes that tiny cross-encoders fragment."""
    return list(dict.fromkeys(_EXACT_CODE_RE.findall(query)))


def _has_exact_code_match(content: str, identifiers: Sequence[str]) -> bool:
    for code in identifiers:
        pattern = rf"(?<![A-Za-z0-9_]){re.escape(code)}(?![A-Za-z0-9_])"
        if re.search(pattern, content, re.IGNORECASE):
            return True
    return False


class FastEmbedReranker:
    """
    Memory-aware ONNX Cross-Encoder reranker (`fastembed.rerank.cross_encoder`).

    - `light` profile: `Xenova/ms-marco-MiniLM-L-6-v2` (~80 MB weights, 512 MB host safe)
    - `base` profile:  `BAAI/bge-reranker-base` (~1.04 GB weights, local Docker / 16 GB host)

    Offloads CPU inference via `asyncio.to_thread` bounded by a concurrency semaphore,
    calibrates raw logits via sigmoid normalization into (0, 1), and applies an exact-code
    grounding floor when a chunk verbatim matches rare alphanumeric error/runbook IDs.
    """

    def __init__(
        self,
        *,
        model_name: str = "Xenova/ms-marco-MiniLM-L-6-v2",
        cpu_semaphore: asyncio.Semaphore | None = None,
    ) -> None:
        self._model_name = model_name
        self._cpu_semaphore = cpu_semaphore or asyncio.Semaphore(2)
        self._encoder: Any | None = None
        self._load_lock = asyncio.Lock()

    @property
    def model_name(self) -> str:
        return self._model_name

    def _load_sync(self) -> Any:
        from fastembed.rerank.cross_encoder import TextCrossEncoder

        logger.info("reranker_loading_onnx", model=self._model_name)
        encoder = TextCrossEncoder(model_name=self._model_name)
        logger.info("reranker_loaded_onnx", model=self._model_name)
        return encoder

    async def _ensure_loaded(self) -> Any:
        if self._encoder is not None:
            return self._encoder
        async with self._load_lock:
            if self._encoder is None:
                self._encoder = await asyncio.to_thread(self._load_sync)
        return self._encoder

    def _score_sync(self, encoder: Any, query: str, texts: list[str]) -> list[float]:
        return [float(s) for s in encoder.rerank(query, texts)]

    async def rerank(
        self,
        query: str,
        candidates: Sequence[RetrievedChunk],
        top_k: int = 5,
    ) -> list[RerankedChunk]:
        if not candidates or top_k <= 0:
            return []

        encoder = await self._ensure_loaded()
        texts = [c.contextual_content for c in candidates]
        exact_codes = extract_exact_code_identifiers(query)

        async with self._cpu_semaphore:
            raw_logits = await asyncio.to_thread(self._score_sync, encoder, query, texts)

        if len(raw_logits) != len(candidates):
            raise RuntimeError(
                f"Reranker returned {len(raw_logits)} scores for {len(candidates)} candidates."
            )

        scored: list[RerankedChunk] = []
        for cand, logit in zip(candidates, raw_logits, strict=True):
            calibrated = sigmoid(logit)
            if exact_codes and _has_exact_code_match(cand.content, exact_codes):
                calibrated = max(calibrated, _EXACT_CODE_FLOOR_SCORE)
            scored.append(
                RerankedChunk(
                    chunk=cand,
                    raw_logit=logit,
                    rerank_score=round(calibrated, 4),
                )
            )

        scored.sort(key=lambda item: (item.rerank_score, item.chunk.rrf_score), reverse=True)
        return scored[:top_k]
