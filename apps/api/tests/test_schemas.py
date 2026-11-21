import uuid

import pytest
from pydantic import ValidationError

from app.db.pool import validate_tenant_id
from app.schemas.ingest import IngestResponse
from app.schemas.query import GroundedLLMOutputSchema, QueryRequest


def test_tenant_id_validation_accepts_valid_slugs() -> None:
    assert validate_tenant_id("acme-corp") == "acme-corp"
    assert validate_tenant_id("globex_io") == "globex_io"
    assert validate_tenant_id("t1") == "t1"


@pytest.mark.parametrize("bad_id", ["", "a", "Acme-Corp", "-acme", "acme corp", "acme;DROP TABLE"])
def test_tenant_id_validation_rejects_invalid_slugs(bad_id: str) -> None:
    with pytest.raises(ValueError):
        validate_tenant_id(bad_id)


def test_query_request_normalizes_and_validates() -> None:
    req = QueryRequest(
        tenant_id="acme-corp",
        query="  Why does ERR_SIG_4092 fail?  ",
        doc_types=["runbook", "api_docs", "runbook"],
    )
    assert req.query == "Why does ERR_SIG_4092 fail?"
    assert req.doc_types == ["api_docs", "runbook"]
    assert req.top_k == 5


def test_query_request_rejects_short_query() -> None:
    with pytest.raises(ValidationError):
        QueryRequest(tenant_id="acme-corp", query="  a ")


def test_ingest_response_validates_sha256_length() -> None:
    resp = IngestResponse(
        status="indexed",
        document_id=uuid.uuid4(),
        tenant_id="acme-corp",
        doc_title="Enterprise SLA",
        doc_type="sla_contract",
        version="v2.0",
        content_hash="a" * 64,
        page_count=12,
        chunk_count=30,
        corpus_version=1,
        latency_ms=420,
    )
    assert resp.status == "indexed"

    with pytest.raises(ValidationError):
        IngestResponse(
            status="indexed",
            document_id=uuid.uuid4(),
            tenant_id="acme-corp",
            doc_title="Enterprise SLA",
            doc_type="sla_contract",
            version="v2.0",
            content_hash="too-short",
            page_count=12,
            chunk_count=30,
            corpus_version=1,
            latency_ms=420,
        )


def test_grounded_llm_schema_roundtrip() -> None:
    raw = (
        '{"status":"answered","answer":"Enforces AES-256 [1].",'
        '"missing_evidence_reason":null,'
        '"used_passages":[{"passage_index":1,"supporting_quote":"AES-256 encryption at rest"}]}'
    )
    parsed = GroundedLLMOutputSchema.model_validate_json(raw)
    assert parsed.status == "answered"
    assert len(parsed.used_passages) == 1
    assert parsed.used_passages[0].passage_index == 1
