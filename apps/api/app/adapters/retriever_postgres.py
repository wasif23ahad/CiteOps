import re
from collections.abc import Sequence
from typing import Any

from pgvector import Vector
from psycopg_pool import AsyncConnectionPool

from app.db.pool import tenant_transaction
from app.domain.models import DocType, RetrievedChunk

_STOPWORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "by",
        "can",
        "do",
        "does",
        "for",
        "from",
        "has",
        "have",
        "how",
        "in",
        "is",
        "it",
        "of",
        "on",
        "or",
        "our",
        "should",
        "that",
        "the",
        "their",
        "this",
        "to",
        "under",
        "we",
        "what",
        "when",
        "where",
        "which",
        "who",
        "why",
        "with",
    }
)

# Preserves codes (ERR_SIG_4092), versions (v2.4.1), standards (AES-256), and sections (4.2)
_TOKEN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*[A-Za-z0-9]|[A-Za-z0-9]")


def build_lexical_or_query(query_text: str, max_terms: int = 16) -> str:
    """
    Convert a natural-language question into a safe OR-joined query string for
    PostgreSQL `websearch_to_tsquery` so long questions do not fail AND matching
    while exact identifiers (`ERR_SIG_4092`, `v2.4.1`, `4.2`) remain preserved.
    """
    raw_tokens = _TOKEN_RE.findall(query_text)
    seen: set[str] = set()
    selected: list[str] = []

    # Prioritize exact alphanumeric/code tokens (digits, underscores, hyphens, dots)
    prioritized = sorted(
        raw_tokens,
        key=lambda t: (
            0
            if any(ch.isdigit() or ch in {"_", "-", "."} for ch in t)
            else 1
        ),
    )

    for tok in prioritized:
        lowered = tok.lower()
        if lowered in _STOPWORDS or lowered in seen:
            continue
        if len(lowered) < 2 and not lowered.isdigit():
            continue
        seen.add(lowered)
        selected.append(tok)
        if len(selected) >= max_terms:
            break

    if not selected:
        return query_text.strip()
    return " OR ".join(selected)


def _row_to_retrieved_chunk(row: tuple[Any, ...]) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=row[0],
        document_id=row[1],
        doc_title=row[2],
        doc_type=row[3],
        version=row[4],
        page_number=row[5],
        section_path=row[6],
        content=row[7],
        contextual_content=row[8],
        rrf_score=float(row[9]),
    )


class PostgresHybridRetriever:
    """
    Single-CTE PostgreSQL 17 hybrid retriever fusing pgvector >= 0.8 HNSW cosine search
    (`hnsw.iterative_scan = relaxed_order`) with dual-dictionary (`simple` + `english`)
    tsvector lexical search via Reciprocal Rank Fusion (k = 60) under strict tenant RLS.
    """

    def __init__(
        self,
        pool: AsyncConnectionPool,
        *,
        dense_limit: int = 50,
        lexical_limit: int = 50,
        rrf_k: int = 60,
        hnsw_ef_search: int = 64,
        hnsw_max_scan_tuples: int = 20000,
    ) -> None:
        self._pool = pool
        self._dense_limit = dense_limit
        self._lexical_limit = lexical_limit
        self._rrf_k = rrf_k
        self._hnsw_ef_search = hnsw_ef_search
        self._hnsw_max_scan_tuples = hnsw_max_scan_tuples

    async def retrieve(
        self,
        *,
        tenant_id: str,
        query_text: str,
        query_embedding: list[float],
        doc_types: Sequence[DocType] | None = None,
        candidate_limit: int = 25,
    ) -> list[RetrievedChunk]:
        lexical_or = build_lexical_or_query(query_text)
        doc_types_param: list[str] | None = list(doc_types) if doc_types else None
        query_vec = Vector(query_embedding)

        async with tenant_transaction(self._pool, tenant_id) as conn:
            # Configure pgvector >= 0.8 iterative HNSW scan locally inside the tenant tx
            await conn.execute("SET LOCAL hnsw.iterative_scan = relaxed_order")
            await conn.execute(
                "SELECT set_config('hnsw.ef_search', %s, true)",
                (str(self._hnsw_ef_search),),
            )
            await conn.execute(
                "SELECT set_config('hnsw.max_scan_tuples', %s, true)",
                (str(self._hnsw_max_scan_tuples),),
            )

            async with conn.cursor() as cur:
                await cur.execute(
                    """
                    WITH dense_candidates AS (
                        SELECT
                            c.id,
                            ROW_NUMBER() OVER (ORDER BY c.embedding <=> %s) AS dense_rank
                        FROM document_chunks c
                        JOIN documents d ON d.id = c.document_id
                        WHERE c.tenant_id = %s
                          AND d.is_active = true
                          AND (%s::text[] IS NULL OR c.doc_type = ANY(%s::text[]))
                        ORDER BY c.embedding <=> %s
                        LIMIT %s
                    ),
                    lexical_query AS (
                        SELECT (
                            websearch_to_tsquery('simple', %s) ||
                            websearch_to_tsquery('english', %s)
                        ) AS q
                    ),
                    lexical_candidates AS (
                        SELECT
                            c.id,
                            ROW_NUMBER() OVER (
                                ORDER BY ts_rank_cd(c.search_tsv, lq.q, 32) DESC
                            ) AS lexical_rank
                        FROM document_chunks c
                        JOIN documents d ON d.id = c.document_id
                        CROSS JOIN lexical_query lq
                        WHERE c.tenant_id = %s
                          AND d.is_active = true
                          AND (%s::text[] IS NULL OR c.doc_type = ANY(%s::text[]))
                          AND c.search_tsv @@ lq.q
                        ORDER BY ts_rank_cd(c.search_tsv, lq.q, 32) DESC
                        LIMIT %s
                    ),
                    rrf_fused AS (
                        SELECT
                            COALESCE(dc.id, lc.id) AS chunk_id,
                            COALESCE(1.0 / (%s + dc.dense_rank), 0.0) +
                            COALESCE(1.0 / (%s + lc.lexical_rank), 0.0) AS rrf_score
                        FROM dense_candidates dc
                        FULL OUTER JOIN lexical_candidates lc ON dc.id = lc.id
                    )
                    SELECT
                        c.id,
                        c.document_id,
                        d.doc_title,
                        c.doc_type,
                        d.version,
                        c.page_number,
                        c.section_path,
                        c.content,
                        c.contextual_content,
                        r.rrf_score
                    FROM rrf_fused r
                    JOIN document_chunks c ON c.id = r.chunk_id
                    JOIN documents d ON d.id = c.document_id
                    ORDER BY r.rrf_score DESC
                    LIMIT %s
                    """,
                    (
                        query_vec,
                        tenant_id,
                        doc_types_param,
                        doc_types_param,
                        query_vec,
                        self._dense_limit,
                        lexical_or,
                        lexical_or,
                        tenant_id,
                        doc_types_param,
                        doc_types_param,
                        self._lexical_limit,
                        self._rrf_k,
                        self._rrf_k,
                        candidate_limit,
                    ),
                )
                rows = await cur.fetchall()
                return [_row_to_retrieved_chunk(row) for row in rows]
