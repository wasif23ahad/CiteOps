import math
import uuid

import pytest

from app.adapters.reranker_fastembed import FastEmbedReranker, sigmoid
from app.domain.models import RetrievedChunk


def _chunk(text: str, rrf: float = 0.02) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=uuid.uuid4(),
        document_id=uuid.uuid4(),
        doc_title="Webhook Spec",
        doc_type="api_docs",
        version="v2.4.1",
        page_number=14,
        section_path="4.3 Errors",
        content=text,
        contextual_content=text,
        rrf_score=rrf,
    )


def test_sigmoid_calibration_is_numerically_stable() -> None:
    assert math.isclose(sigmoid(0.0), 0.5, rel_tol=1e-6)
    assert 0.0 < sigmoid(-100.0) < 1e-40
    assert 0.9999 < sigmoid(100.0) <= 1.0
    assert sigmoid(3.0) > sigmoid(0.5) > sigmoid(-3.0)


@pytest.mark.asyncio
async def test_reranker_sorts_by_calibrated_score_and_respects_top_k() -> None:
    reranker = FastEmbedReranker(model_name="fake-cross-encoder")

    class _FakeEncoder:
        def rerank(self, query: str, documents: list[str]) -> list[float]:
            # Return raw unbounded cross-encoder logits
            return [-5.0, 4.2, 0.2]

    reranker._encoder = _FakeEncoder()  # noqa: SLF001

    candidates = [
        _chunk("Unrelated weather passage"),
        _chunk("ERR_SIG_4092 raw buffer HMAC verification"),
        _chunk("General webhook overview"),
    ]
    top2 = await reranker.rerank("ERR_SIG_4092", candidates, top_k=2)

    assert len(top2) == 2
    assert "ERR_SIG_4092" in top2[0].chunk.content
    assert top2[0].raw_logit == 4.2
    assert 0.98 < top2[0].rerank_score <= 1.0
    assert top2[1].rerank_score < top2[0].rerank_score
    assert 0.5 < top2[1].rerank_score < 0.6


@pytest.mark.asyncio
async def test_reranker_boosts_verbatim_alphanumeric_code_identifier_matches() -> None:
    reranker = FastEmbedReranker(model_name="fake-cross-encoder")

    class _LowScoreEncoder:
        def rerank(self, query: str, documents: list[str]) -> list[float]:
            # Simulate MS MARCO subword fragmentation returning low raw logits for rare code
            return [-4.8, -5.2]

    reranker._encoder = _LowScoreEncoder()  # noqa: SLF001

    candidates = [
        _chunk("Custom Error Code ERR_GLOBEX_9901: Run globex-hsmctl rotate --slot 4."),
        _chunk("General unrelated relay rotation guidance."),
    ]
    ranked = await reranker.rerank("How do I resolve ERR_GLOBEX_9901?", candidates, top_k=2)

    assert "ERR_GLOBEX_9901" in ranked[0].chunk.content
    assert ranked[0].rerank_score >= 0.75
    assert ranked[1].rerank_score < 0.05
