import re
from collections.abc import Sequence
from dataclasses import dataclass

from app.domain.models import DocumentChunkDraft, ParsedPage

_HEADING_RE = re.compile(r"^(#{1,3})\s+(.+?)\s*$")
_WORD_RE = re.compile(r"\S+")


def estimate_tokens(text: str) -> int:
    """Fast, dependency-free token approximation (~1.33 tokens per whitespace word)."""
    words = len(_WORD_RE.findall(text))
    if words == 0:
        return 0
    return max(1, (words * 4 + 2) // 3)


@dataclass(slots=True)
class _SemanticBlock:
    kind: str  # "heading" | "code" | "table" | "prose"
    text: str
    section_path: str
    page_number: int


class StructureAwareChunker:
    """
    Splits page-indexed Markdown along H1-H3 headings while keeping Markdown tables
    and fenced code blocks intact, then enriches chunks with contextual breadcrumbs.
    """

    def __init__(
        self,
        target_tokens: int = 450,
        max_tokens: int = 600,
        overlap_tokens: int = 65,
    ) -> None:
        if target_tokens <= 0 or max_tokens < target_tokens:
            raise ValueError("Require 0 < target_tokens <= max_tokens.")
        if overlap_tokens < 0 or overlap_tokens >= target_tokens:
            raise ValueError("Require 0 <= overlap_tokens < target_tokens.")
        self._target_tokens = target_tokens
        self._max_tokens = max_tokens
        self._overlap_tokens = overlap_tokens

    def chunk(
        self,
        pages: Sequence[ParsedPage],
        *,
        doc_title: str,
        version: str,
    ) -> list[DocumentChunkDraft]:
        heading_stack: dict[int, str] = {}
        drafts: list[DocumentChunkDraft] = []
        chunk_index = 0

        for page in pages:
            blocks = self._extract_blocks(page, heading_stack)
            if not blocks:
                continue

            page_chunks = self._pack_blocks(blocks)
            for section_path, content in page_chunks:
                cleaned = content.strip()
                if not cleaned:
                    continue
                breadcrumb_section = section_path or "General"
                contextual = (
                    f"[Document: {doc_title} | Version: {version} | "
                    f"Section: {breadcrumb_section} | Page: {page.page_number}]\n"
                    f"{cleaned}"
                )
                drafts.append(
                    DocumentChunkDraft(
                        chunk_index=chunk_index,
                        page_number=page.page_number,
                        section_path=breadcrumb_section,
                        content=cleaned,
                        contextual_content=contextual,
                        token_count=estimate_tokens(cleaned),
                    )
                )
                chunk_index += 1

        return drafts

    def _extract_blocks(
        self, page: ParsedPage, heading_stack: dict[int, str]
    ) -> list[_SemanticBlock]:
        lines = page.markdown_text.split("\n")
        blocks: list[_SemanticBlock] = []
        idx = 0

        def current_section() -> str:
            return " > ".join(heading_stack[lvl] for lvl in sorted(heading_stack))

        while idx < len(lines):
            line = lines[idx]
            stripped = line.strip()

            if not stripped:
                idx += 1
                continue

            # 1. Markdown heading (H1-H3)
            heading_match = _HEADING_RE.match(stripped)
            if heading_match:
                level = len(heading_match.group(1))
                title = heading_match.group(2).strip()
                heading_stack[level] = title
                for deeper in [k for k in heading_stack if k > level]:
                    del heading_stack[deeper]
                blocks.append(
                    _SemanticBlock(
                        kind="heading",
                        text=stripped,
                        section_path=current_section(),
                        page_number=page.page_number,
                    )
                )
                idx += 1
                continue

            # 2. Fenced code block (kept atomic)
            if stripped.startswith("```"):
                fence_lines = [line]
                idx += 1
                while idx < len(lines):
                    fence_lines.append(lines[idx])
                    if lines[idx].strip().startswith("```"):
                        idx += 1
                        break
                    idx += 1
                blocks.append(
                    _SemanticBlock(
                        kind="code",
                        text="\n".join(fence_lines),
                        section_path=current_section(),
                        page_number=page.page_number,
                    )
                )
                continue

            # 3. Markdown table (kept atomic)
            if stripped.startswith("|") and "|" in stripped[1:]:
                table_lines = [line]
                idx += 1
                while idx < len(lines):
                    nxt = lines[idx].strip()
                    if nxt.startswith("|") and "|" in nxt[1:]:
                        table_lines.append(lines[idx])
                        idx += 1
                    else:
                        break
                blocks.append(
                    _SemanticBlock(
                        kind="table",
                        text="\n".join(table_lines),
                        section_path=current_section(),
                        page_number=page.page_number,
                    )
                )
                continue

            # 4. Prose / list paragraph
            para_lines = [line]
            idx += 1
            while idx < len(lines):
                nxt = lines[idx].strip()
                if (
                    not nxt
                    or _HEADING_RE.match(nxt)
                    or nxt.startswith("```")
                    or (nxt.startswith("|") and "|" in nxt[1:])
                ):
                    break
                para_lines.append(lines[idx])
                idx += 1

            blocks.append(
                _SemanticBlock(
                    kind="prose",
                    text="\n".join(para_lines),
                    section_path=current_section(),
                    page_number=page.page_number,
                )
            )

        return blocks

    def _pack_blocks(self, blocks: list[_SemanticBlock]) -> list[tuple[str, str]]:
        packed: list[tuple[str, str]] = []
        current_texts: list[str] = []
        current_tokens = 0
        current_section = blocks[0].section_path

        def flush() -> None:
            nonlocal current_texts, current_tokens
            if current_texts:
                packed.append((current_section, "\n\n".join(current_texts)))
                current_texts = []
                current_tokens = 0

        for block in blocks:
            block_tokens = estimate_tokens(block.text)

            # Start a fresh chunk at major heading transitions when current buffer has substance
            if (
                block.kind == "heading"
                and current_texts
                and current_tokens >= self._target_tokens // 3
            ):
                flush()
                current_section = block.section_path

            # Oversized single block (table, code, or huge paragraph): split safely by lines/words
            if block_tokens > self._max_tokens:
                flush()
                current_section = block.section_path
                for piece in self._split_oversized_block(block):
                    packed.append((block.section_path, piece))
                continue

            # If adding this block would exceed max_tokens, flush and retain prose overlap
            if current_texts and (current_tokens + block_tokens > self._max_tokens):
                overlap_text = self._build_overlap(current_texts)
                flush()
                current_section = block.section_path
                if overlap_text and block.kind == "prose":
                    current_texts = [overlap_text]
                    current_tokens = estimate_tokens(overlap_text)

            if not current_texts:
                current_section = block.section_path
            elif block.kind == "heading" and (
                not current_section or block.section_path.startswith(f"{current_section} > ")
            ):
                current_section = block.section_path

            current_texts.append(block.text)
            current_tokens += block_tokens

            # Flush cleanly when reaching target window on a non-heading boundary
            if current_tokens >= self._target_tokens and block.kind != "heading":
                overlap_text = self._build_overlap(current_texts)
                flush()
                if overlap_text:
                    current_texts = [overlap_text]
                    current_tokens = estimate_tokens(overlap_text)

        # Avoid emitting a trailing chunk that consists purely of carried-over overlap text
        if current_texts:
            joined = "\n\n".join(current_texts)
            if not packed or not packed[-1][1].endswith(joined):
                packed.append((current_section, joined))

        return packed

    def _build_overlap(self, texts: list[str]) -> str:
        if self._overlap_tokens <= 0:
            return ""
        # Never duplicate whole tables or code blocks as overlap
        last_text = texts[-1].strip()
        if last_text.startswith("```") or last_text.startswith("|"):
            return ""
        words = last_text.split()
        overlap_words = max(1, (self._overlap_tokens * 3) // 4)
        if len(words) <= overlap_words:
            return last_text
        return " ".join(words[-overlap_words:])

    def _split_oversized_block(self, block: _SemanticBlock) -> list[str]:
        if block.kind == "table":
            return self._split_oversized_table(block.text)
        if block.kind == "code":
            return self._split_oversized_code(block.text)
        return self._split_oversized_prose(block.text)

    def _split_oversized_table(self, text: str) -> list[str]:
        lines = text.split("\n")
        if len(lines) <= 2:
            return [text]
        header = lines[:2]
        header_tokens = estimate_tokens("\n".join(header))
        pieces: list[str] = []
        buf = list(header)
        buf_tokens = header_tokens
        for row in lines[2:]:
            row_tokens = estimate_tokens(row)
            if len(buf) > 2 and buf_tokens + row_tokens > self._max_tokens:
                pieces.append("\n".join(buf))
                buf = list(header) + [row]
                buf_tokens = header_tokens + row_tokens
            else:
                buf.append(row)
                buf_tokens += row_tokens
        if len(buf) > 2:
            pieces.append("\n".join(buf))
        return pieces or [text]

    def _split_oversized_code(self, text: str) -> list[str]:
        lines = text.split("\n")
        opening = lines[0] if lines and lines[0].strip().startswith("```") else "```"
        body = lines[1:-1] if len(lines) >= 2 and lines[-1].strip().startswith("```") else lines
        pieces: list[str] = []
        buf: list[str] = []
        buf_tokens = 0
        limit = max(64, self._max_tokens - 10)
        for line in body:
            lt = estimate_tokens(line)
            if buf and buf_tokens + lt > limit:
                pieces.append(f"{opening}\n" + "\n".join(buf) + "\n```")
                buf = [line]
                buf_tokens = lt
            else:
                buf.append(line)
                buf_tokens += lt
        if buf:
            pieces.append(f"{opening}\n" + "\n".join(buf) + "\n```")
        return pieces or [text]

    def _split_oversized_prose(self, text: str) -> list[str]:
        words = text.split()
        max_words = max(32, (self._target_tokens * 3) // 4)
        overlap_words = max(0, (self._overlap_tokens * 3) // 4)
        step = max(1, max_words - overlap_words)
        pieces: list[str] = []
        for start in range(0, len(words), step):
            segment = words[start : start + max_words]
            if not segment:
                break
            pieces.append(" ".join(segment))
            if start + max_words >= len(words):
                break
        return pieces
