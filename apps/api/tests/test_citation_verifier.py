import uuid

from app.domain.models import (
    GroundedLLMResult,
    LLMUsedPassage,
    RerankedChunk,
    RetrievedChunk,
)
from app.services.verifier import CitationVerifierAndHydrator


def _make_passage(
    *,
    doc_title: str,
    page_number: int,
    content: str,
    score: float = 0.94,
) -> RerankedChunk:
    return RerankedChunk(
        chunk=RetrievedChunk(
            chunk_id=uuid.uuid4(),
            document_id=uuid.uuid4(),
            doc_title=doc_title,
            doc_type="api_docs",
            version="v2.4.1",
            page_number=page_number,
            section_path="4.3 Webhook Error Codes > ERR_SIG_4092",
            content=content,
            contextual_content=content,
            rrf_score=0.032,
        ),
        raw_logit=2.75,
        rerank_score=score,
    )


def test_verifier_hydrates_authoritative_db_metadata_and_verbatim_excerpt() -> None:
    p1 = _make_passage(
        doc_title="Webhook Integration & Error Reference",
        page_number=14,
        content=(
            "ERR_SIG_4092 is triggered on SDK v2.4.1 when middleware parses JSON "
            "prior to HMAC-SHA256 verification. Pass the unparsed raw byte buffer to "
            "verifySignature()."
        ),
        score=0.94,
    )
    llm_result = GroundedLLMResult(
        status="answered",
        answer=(
            "ERR_SIG_4092 happens on SDK v2.4.1 when middleware parses JSON before "
            "HMAC-SHA256 validation [1]."
        ),
        used_passages=(
            LLMUsedPassage(
                passage_index=1,
                supporting_quote="middleware parses JSON prior to HMAC-SHA256 verification",
            ),
        ),
    )

    outcome = CitationVerifierAndHydrator().verify(llm_result, [p1])
    assert outcome.status == "answered"
    assert outcome.downgraded is False
    assert len(outcome.citations) == 1

    c = outcome.citations[0]
    assert c.citation_index == 1
    assert c.document_id == p1.chunk.document_id
    assert c.page_number == 14
    assert c.rerank_score == 0.94
    assert "HMAC-SHA256 verification" in c.excerpt


def test_verifier_downgrades_on_out_of_bounds_citation_index() -> None:
    p1 = _make_passage(doc_title="Webhook Spec", page_number=14, content="ERR_SIG_4092 details.")
    llm_result = GroundedLLMResult(
        status="answered",
        answer="ERR_SIG_4092 is documented here [1] and also in [9].",
        used_passages=(LLMUsedPassage(passage_index=1, supporting_quote="ERR_SIG_4092"),),
    )

    outcome = CitationVerifierAndHydrator().verify(llm_result, [p1])
    assert outcome.status == "insufficient_evidence"
    assert outcome.downgraded is True
    assert outcome.citations == []
    assert outcome.missing_evidence_reason is not None


def test_verifier_downgrades_when_answered_without_inline_citations() -> None:
    p1 = _make_passage(doc_title="SLA", page_number=4, content="AES-256 encryption at rest.")
    llm_result = GroundedLLMResult(
        status="answered",
        answer="CloudPulse enforces AES-256 encryption at rest.",
        used_passages=(),
    )

    outcome = CitationVerifierAndHydrator().verify(llm_result, [p1])
    assert outcome.status == "insufficient_evidence"
    assert outcome.downgraded is True
    assert outcome.citations == []


def test_verifier_replaces_paraphrased_quote_with_verbatim_source_chunk_text() -> None:
    source_text = "A HIPAA Business Associate Agreement (BAA) is NOT included by default."
    p1 = _make_passage(doc_title="SOC 2 Policy", page_number=5, content=source_text, score=0.91)
    llm_result = GroundedLLMResult(
        status="answered",
        answer="HIPAA BAA requires a separate enterprise addendum and is not default [1].",
        used_passages=(
            LLMUsedPassage(
                passage_index=1,
                supporting_quote="Totally paraphrased hallucinated quote string",
            ),
        ),
    )

    outcome = CitationVerifierAndHydrator().verify(llm_result, [p1])
    assert outcome.status == "answered"
    assert outcome.citations[0].excerpt == source_text
