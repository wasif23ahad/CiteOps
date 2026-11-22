import pymupdf
import pytest

from app.adapters.parser_pymupdf import (
    PyMuPDFDocumentParser,
    UnsupportedDocumentFormatError,
)
from app.services.chunker import StructureAwareChunker, estimate_tokens


def _build_two_page_pdf() -> bytes:
    doc = pymupdf.open()
    page1 = doc.new_page()
    page1.insert_text((72, 72), "Enterprise SLA Overview\nSection 4.2 enforces AES-256 at rest.")
    page2 = doc.new_page()
    page2.insert_text((72, 72), "Disaster Recovery\nGuaranteed Sev-1 RTO failover is 15 minutes.")
    raw = doc.tobytes()
    doc.close()
    return raw


def test_pdf_parser_preserves_page_numbers() -> None:
    parser = PyMuPDFDocumentParser()
    pages = parser.parse(_build_two_page_pdf(), "enterprise_sla.pdf")

    assert len(pages) == 2
    assert pages[0].page_number == 1
    assert "AES-256" in pages[0].markdown_text
    assert pages[1].page_number == 2
    assert "15 minutes" in pages[1].markdown_text


def test_markdown_parser_honors_explicit_page_markers() -> None:
    md = (
        b"<!-- page: 1 -->\n# Intro\nWelcome.\n\n"
        b"<!-- page: 14 -->\n## 4.3 Webhook Errors\n`ERR_SIG_4092` on SDK `v2.4.1`.\n"
    )
    parser = PyMuPDFDocumentParser()
    pages = parser.parse(md, "webhooks.md")

    assert [p.page_number for p in pages] == [1, 14]
    assert "ERR_SIG_4092" in pages[1].markdown_text


def test_parser_rejects_unsupported_extension_and_empty_bytes() -> None:
    parser = PyMuPDFDocumentParser()
    with pytest.raises(UnsupportedDocumentFormatError):
        parser.parse(b"hello", "notes.docx")
    with pytest.raises(UnsupportedDocumentFormatError):
        parser.parse(b"", "empty.md")


def test_chunker_preserves_tables_code_blocks_and_breadcrumbs() -> None:
    md = (
        b"<!-- page: 14 -->\n"
        b"# Webhook Guide\n"
        b"## 4.3 Webhook Error Codes\n"
        b"### ERR_SIG_4092\n"
        b"Payload digest mismatch triggered when middleware mutates JSON whitespace.\n\n"
        b"| Version | Behavior | Status |\n"
        b"| :--- | :--- | :--- |\n"
        b"| v2.4.1 | Strict raw bytes | Current |\n"
        b"| v2.4.0 | Permissive fallback | Rollback |\n\n"
        b"```ts\n"
        b"app.post('/webhooks', express.raw({ type: 'application/json' }), handler);\n"
        b"```\n"
    )

    parser = PyMuPDFDocumentParser()
    pages = parser.parse(md, "webhook_guide.md")

    chunker = StructureAwareChunker(target_tokens=450, max_tokens=600, overlap_tokens=65)
    chunks = chunker.chunk(pages, doc_title="Webhook Reference", version="v2.4.1")

    assert len(chunks) == 1
    chunk = chunks[0]
    assert chunk.page_number == 14
    assert "Webhook Guide" in chunk.section_path
    assert "ERR_SIG_4092" in chunk.section_path
    assert "| v2.4.1 | Strict raw bytes | Current |" in chunk.content
    assert "express.raw({ type: 'application/json' })" in chunk.content
    assert chunk.contextual_content.startswith(
        "[Document: Webhook Reference | Version: v2.4.1 |"
    )
    assert "| Page: 14]" in chunk.contextual_content


def test_chunker_respects_max_token_ceiling_on_long_prose() -> None:
    long_prose = " ".join(f"word{i}" for i in range(900))
    md = f"<!-- page: 3 -->\n# Long Policy\n\n{long_prose}\n".encode()
    pages = PyMuPDFDocumentParser().parse(md, "long.md")

    chunker = StructureAwareChunker(target_tokens=200, max_tokens=260, overlap_tokens=40)
    chunks = chunker.chunk(pages, doc_title="Long Policy", version="v1.0")

    assert len(chunks) >= 4
    assert all(c.page_number == 3 for c in chunks)
    assert all(estimate_tokens(c.content) <= 275 for c in chunks)
