import re
from pathlib import Path

import pymupdf
import pymupdf4llm

from app.domain.models import ParsedPage

SUPPORTED_EXTENSIONS = frozenset({".pdf", ".md", ".markdown", ".txt"})
_PAGE_MARKER_RE = re.compile(r"^\s*<!--\s*page\s*:\s*(\d+)\s*-->\s*$", re.IGNORECASE)


class UnsupportedDocumentFormatError(ValueError):
    """Raised when an uploaded file has an unsupported extension or empty content."""


class PyMuPDFDocumentParser:
    """Extracts page-indexed Markdown from PDFs (via pymupdf4llm) and Markdown/text files."""

    def parse(self, file_bytes: bytes, filename: str) -> list[ParsedPage]:
        if not file_bytes:
            raise UnsupportedDocumentFormatError("Uploaded file is empty.")

        ext = Path(filename).suffix.lower()
        if ext not in SUPPORTED_EXTENSIONS:
            supported = ", ".join(sorted(SUPPORTED_EXTENSIONS))
            raise UnsupportedDocumentFormatError(
                f"Unsupported file extension '{ext}'. Supported formats: {supported}."
            )

        if ext == ".pdf":
            return self._parse_pdf(file_bytes)
        return self._parse_markdown_or_text(file_bytes)

    def _parse_pdf(self, file_bytes: bytes) -> list[ParsedPage]:
        if not file_bytes.lstrip().startswith(b"%PDF-"):
            raise UnsupportedDocumentFormatError(
                "Uploaded file does not have a valid PDF header (%PDF-)."
            )

        pages: list[ParsedPage] = []
        try:
            with pymupdf.open(stream=file_bytes, filetype="pdf") as pdf_doc:
                raw_chunks = pymupdf4llm.to_markdown(pdf_doc, page_chunks=True)
                for idx, item in enumerate(raw_chunks, start=1):
                    if isinstance(item, dict):
                        text = str(item.get("text", "")).strip()
                        meta = item.get("metadata") or {}
                        raw_page = meta.get("page_number") or meta.get("page")
                        if isinstance(raw_page, int):
                            # pymupdf4llm page metadata can be 1-based or 0-based depending on
                            # version; idx is strictly 1..N matching the PDF page sequence.
                            page_number = idx if raw_page in (idx - 1, idx) else max(1, raw_page)
                        else:
                            page_number = idx
                    else:
                        text = str(item).strip()
                        page_number = idx

                    if text:
                        pages.append(ParsedPage(page_number=page_number, markdown_text=text))
        except UnsupportedDocumentFormatError:
            raise
        except Exception as exc:
            raise UnsupportedDocumentFormatError(
                "Unable to parse PDF document (file may be corrupted or encrypted)."
            ) from exc

        if not pages:
            raise UnsupportedDocumentFormatError(
                "No extractable text found in PDF document."
            )
        return pages

    def _parse_markdown_or_text(self, file_bytes: bytes) -> list[ParsedPage]:
        decoded = file_bytes.decode("utf-8", errors="replace").replace("\r\n", "\n")

        # Support form-feed (\f) splits if explicit HTML page markers are absent
        if "\f" in decoded and not _PAGE_MARKER_RE.search(decoded):
            segments = decoded.split("\f")
            pages = [
                ParsedPage(page_number=i, markdown_text=seg.strip())
                for i, seg in enumerate(segments, start=1)
                if seg.strip()
            ]
            if pages:
                return pages

        current_page = 1
        buffers: dict[int, list[str]] = {}

        for line in decoded.split("\n"):
            match = _PAGE_MARKER_RE.match(line)
            if match:
                current_page = max(1, int(match.group(1)))
                continue
            buffers.setdefault(current_page, []).append(line)

        pages = [
            ParsedPage(page_number=page_num, markdown_text="\n".join(lines).strip())
            for page_num, lines in sorted(buffers.items())
            if "\n".join(lines).strip()
        ]
        if not pages:
            raise UnsupportedDocumentFormatError("Document contains no readable text.")
        return pages
