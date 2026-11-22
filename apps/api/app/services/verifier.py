import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from app.core.logging import get_logger
from app.domain.models import GroundedLLMResult, RerankedChunk, VerifiedCitation

logger = get_logger(__name__)

_CITATION_MARKER_RE = re.compile(r"\[(\d+)\]")
_WHITESPACE_RE = re.compile(r"\s+")
_WORD_RE = re.compile(r"[a-z0-9_.-]+")
_MAX_EXCERPT_CHARS = 340


@dataclass(frozen=True, slots=True)
class VerificationOutcome:
    status: Literal["answered", "insufficient_evidence"]
    answer: str
    missing_evidence_reason: str | None
    citations: list[VerifiedCitation]
    downgraded: bool = False


def _normalize_ws(text: str) -> str:
    return _WHITESPACE_RE.sub(" ", text).strip()


def _extract_verbatim_excerpt(source_content: str, candidate_quote: str) -> str:
    """
    Guarantee the citation excerpt shown in the Source Inspector Drawer is strictly
    verbatim text from `source_content`.
    """
    cleaned_source = source_content.strip()
    if len(cleaned_source) <= _MAX_EXCERPT_CHARS and not candidate_quote:
        return cleaned_source

    norm_quote = _normalize_ws(candidate_quote)
    if norm_quote:
        # 1. Exact case-insensitive substring match against normalized source
        norm_source = _normalize_ws(cleaned_source)
        pos = norm_source.lower().find(norm_quote.lower())
        if pos != -1:
            target_end = min(len(norm_source), pos + max(len(norm_quote), 180))
            if target_end < len(norm_source):
                # Snap forward to sentence boundary if close, otherwise cleanly to word boundary
                sentence_end = norm_source.find(".", pos + len(norm_quote), target_end + 80)
                if sentence_end != -1 and (sentence_end + 1 - pos) <= _MAX_EXCERPT_CHARS:
                    snippet = norm_source[pos : sentence_end + 1]
                else:
                    raw_slice = norm_source[pos:target_end]
                    if " " in raw_slice:
                        raw_slice = raw_slice.rsplit(" ", 1)[0]
                    snippet = raw_slice.rstrip(" ,;:-") + "..."
            else:
                snippet = norm_source[pos:target_end]
            if len(snippet) > _MAX_EXCERPT_CHARS:
                snippet = snippet[: _MAX_EXCERPT_CHARS - 3].rsplit(" ", 1)[0].rstrip() + "..."
            return snippet

        # 2. Pick the highest token-overlap sentence/line window from the verbatim chunk
        quote_tokens = set(_WORD_RE.findall(norm_quote.lower()))
        if quote_tokens:
            segments = [
                seg.strip()
                for seg in re.split(r"(?<=[.!?])\s+|\n+", cleaned_source)
                if seg.strip()
            ]
            best_seg = ""
            best_overlap = 0.0
            for seg in segments:
                seg_tokens = set(_WORD_RE.findall(seg.lower()))
                if not seg_tokens:
                    continue
                overlap = len(quote_tokens & seg_tokens) / len(quote_tokens)
                if overlap > best_overlap:
                    best_overlap = overlap
                    best_seg = seg
            if best_seg and best_overlap >= 0.35:
                if len(best_seg) > _MAX_EXCERPT_CHARS:
                    return best_seg[: _MAX_EXCERPT_CHARS - 3].rstrip() + "..."
                return best_seg

    # 3. Fallback: leading verbatim window from the retrieved chunk
    norm_fallback = _normalize_ws(cleaned_source)
    if len(norm_fallback) <= _MAX_EXCERPT_CHARS:
        return norm_fallback
    return norm_fallback[: _MAX_EXCERPT_CHARS - 3].rstrip() + "..."


class CitationVerifierAndHydrator:
    """
    Deterministic post-generation guardrail verifying inline `[n]` citation bounds,
    grounding excerpts against source passages, and hydrating authoritative metadata
    strictly from PostgreSQL records.
    """

    def verify(
        self,
        llm_result: GroundedLLMResult,
        passages: Sequence[RerankedChunk],
    ) -> VerificationOutcome:
        if llm_result.status == "insufficient_evidence":
            return VerificationOutcome(
                status="insufficient_evidence",
                answer=(
                    llm_result.answer
                    or "Insufficient evidence in the tenant knowledge base to answer this question."
                ),
                missing_evidence_reason=(
                    llm_result.missing_evidence_reason
                    or "Retrieved passages did not directly substantiate an answer."
                ),
                citations=[],
                downgraded=False,
            )

        max_index = len(passages)
        inline_indices = [int(m) for m in _CITATION_MARKER_RE.findall(llm_result.answer)]

        # Reject out-of-bounds citation markers (e.g. [9] when only 5 passages were provided)
        out_of_bounds = [idx for idx in inline_indices if idx < 1 or idx > max_index]
        if out_of_bounds:
            logger.warning(
                "citation_verification_downgrade_out_of_bounds",
                invalid_indices=out_of_bounds,
                max_index=max_index,
            )
            return VerificationOutcome(
                status="insufficient_evidence",
                answer=(
                    "Unable to verify citations for the generated answer against the "
                    "retrieved tenant documentation."
                ),
                missing_evidence_reason=(
                    f"Citation verifier rejected out-of-bounds references {out_of_bounds}."
                ),
                citations=[],
                downgraded=True,
            )

        # Require at least one grounded inline citation when answering
        ordered_unique_indices: list[int] = []
        for idx in inline_indices:
            if idx not in ordered_unique_indices:
                ordered_unique_indices.append(idx)

        if not ordered_unique_indices:
            logger.warning("citation_verification_downgrade_missing_citations")
            return VerificationOutcome(
                status="insufficient_evidence",
                answer=(
                    "Unable to provide a citation-verified answer from the available "
                    "tenant documentation."
                ),
                missing_evidence_reason=(
                    "Model output did not include verifiable inline passage citations."
                ),
                citations=[],
                downgraded=True,
            )

        quotes_by_index = {
            p.passage_index: p.supporting_quote
            for p in llm_result.used_passages
            if 1 <= p.passage_index <= max_index
        }

        hydrated: list[VerifiedCitation] = []
        for idx in ordered_unique_indices:
            reranked = passages[idx - 1]
            chunk = reranked.chunk
            excerpt = _extract_verbatim_excerpt(
                chunk.content,
                quotes_by_index.get(idx, ""),
            )
            hydrated.append(
                VerifiedCitation(
                    citation_index=idx,
                    document_id=chunk.document_id,
                    doc_title=chunk.doc_title,
                    doc_type=chunk.doc_type,
                    version=chunk.version,
                    page_number=chunk.page_number,
                    section_path=chunk.section_path,
                    rerank_score=reranked.rerank_score,
                    excerpt=excerpt,
                )
            )

        return VerificationOutcome(
            status="answered",
            answer=llm_result.answer,
            missing_evidence_reason=None,
            citations=hydrated,
            downgraded=False,
        )
