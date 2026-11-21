from collections.abc import Sequence
from typing import Any
from uuid import UUID

from pgvector import Vector
from psycopg_pool import AsyncConnectionPool

from app.db.pool import tenant_transaction
from app.domain.models import DocType, DocumentChunkDraft, DocumentRecord


def _row_to_document(row: tuple[Any, ...]) -> DocumentRecord:
    return DocumentRecord(
        id=row[0],
        tenant_id=row[1],
        doc_title=row[2],
        doc_type=row[3],
        version=row[4],
        source_filename=row[5],
        content_hash=row[6].strip(),
        embedding_model=row[7],
        embedding_dim=row[8],
        page_count=row[9],
        chunk_count=row[10],
        is_active=row[11],
        created_at=row[12],
    )


_DOC_COLUMNS = """
    id, tenant_id, doc_title, doc_type, version, source_filename,
    content_hash, embedding_model, embedding_dim, page_count,
    chunk_count, is_active, created_at
"""


class PostgresDocumentRepository:
    """RLS-enforced PostgreSQL repository for tenants, documents, and embedded chunks."""

    def __init__(self, pool: AsyncConnectionPool) -> None:
        self._pool = pool

    async def ensure_tenant(self, tenant_id: str, name: str | None = None) -> None:
        display_name = name or tenant_id
        async with tenant_transaction(self._pool, tenant_id) as conn:
            await conn.execute(
                """
                INSERT INTO tenants (id, name)
                VALUES (%s, %s)
                ON CONFLICT (id) DO NOTHING
                """,
                (tenant_id, display_name),
            )

    async def find_active_by_hash(
        self, tenant_id: str, content_hash: str
    ) -> DocumentRecord | None:
        async with tenant_transaction(self._pool, tenant_id) as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    f"""
                    SELECT {_DOC_COLUMNS}
                    FROM documents
                    WHERE tenant_id = %s
                      AND content_hash = %s
                      AND is_active = true
                    LIMIT 1
                    """,
                    (tenant_id, content_hash),
                )
                row = await cur.fetchone()
                return _row_to_document(row) if row is not None else None

    async def save_document_with_chunks(
        self,
        *,
        tenant_id: str,
        doc_title: str,
        doc_type: DocType,
        version: str,
        source_filename: str,
        content_hash: str,
        embedding_model: str,
        embedding_dim: int,
        page_count: int,
        chunks: Sequence[DocumentChunkDraft],
        embeddings: Sequence[list[float]],
        replace_existing: bool = True,
    ) -> DocumentRecord:
        if len(chunks) != len(embeddings):
            raise ValueError("chunks and embeddings length mismatch.")

        async with tenant_transaction(self._pool, tenant_id) as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    """
                    INSERT INTO tenants (id, name)
                    VALUES (%s, %s)
                    ON CONFLICT (id) DO NOTHING
                    """,
                    (tenant_id, tenant_id),
                )

                if replace_existing:
                    await cur.execute(
                        """
                        UPDATE documents
                        SET is_active = false
                        WHERE tenant_id = %s
                          AND doc_title = %s
                          AND doc_type = %s
                          AND content_hash <> %s
                          AND is_active = true
                        """,
                        (tenant_id, doc_title, doc_type, content_hash),
                    )

                # Upsert supports cleanly reactivating a previously superseded content_hash
                await cur.execute(
                    f"""
                    INSERT INTO documents (
                        tenant_id, doc_title, doc_type, version, source_filename,
                        content_hash, embedding_model, embedding_dim, page_count,
                        chunk_count, is_active
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, true)
                    ON CONFLICT (tenant_id, content_hash) DO UPDATE SET
                        doc_title = EXCLUDED.doc_title,
                        doc_type = EXCLUDED.doc_type,
                        version = EXCLUDED.version,
                        source_filename = EXCLUDED.source_filename,
                        embedding_model = EXCLUDED.embedding_model,
                        embedding_dim = EXCLUDED.embedding_dim,
                        page_count = EXCLUDED.page_count,
                        chunk_count = EXCLUDED.chunk_count,
                        is_active = true
                    RETURNING {_DOC_COLUMNS}
                    """,
                    (
                        tenant_id,
                        doc_title,
                        doc_type,
                        version,
                        source_filename,
                        content_hash,
                        embedding_model,
                        embedding_dim,
                        page_count,
                        len(chunks),
                    ),
                )
                doc_row = await cur.fetchone()
                if doc_row is None:
                    raise RuntimeError("Failed to persist document metadata.")
                record = _row_to_document(doc_row)

                # Clear stale chunks if reactivating an existing document_id
                await cur.execute(
                    "DELETE FROM document_chunks WHERE document_id = %s AND tenant_id = %s",
                    (record.id, tenant_id),
                )

                if chunks:
                    chunk_rows = [
                        (
                            tenant_id,
                            record.id,
                            doc_type,
                            chunk.chunk_index,
                            chunk.page_number,
                            chunk.section_path,
                            chunk.content,
                            chunk.contextual_content,
                            chunk.token_count,
                            Vector(vec),
                        )
                        for chunk, vec in zip(chunks, embeddings, strict=True)
                    ]
                    await cur.executemany(
                        """
                        INSERT INTO document_chunks (
                            tenant_id, document_id, doc_type, chunk_index,
                            page_number, section_path, content, contextual_content,
                            token_count, embedding
                        )
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        """,
                        chunk_rows,
                    )

                return record

    async def list_documents(
        self, tenant_id: str, doc_type: DocType | None = None
    ) -> list[DocumentRecord]:
        async with tenant_transaction(self._pool, tenant_id) as conn:
            async with conn.cursor() as cur:
                if doc_type is not None:
                    await cur.execute(
                        f"""
                        SELECT {_DOC_COLUMNS}
                        FROM documents
                        WHERE tenant_id = %s
                          AND is_active = true
                          AND doc_type = %s
                        ORDER BY created_at DESC
                        """,
                        (tenant_id, doc_type),
                    )
                else:
                    await cur.execute(
                        f"""
                        SELECT {_DOC_COLUMNS}
                        FROM documents
                        WHERE tenant_id = %s
                          AND is_active = true
                        ORDER BY created_at DESC
                        """,
                        (tenant_id,),
                    )
                rows = await cur.fetchall()
                return [_row_to_document(r) for r in rows]

    async def delete_document(self, tenant_id: str, document_id: UUID) -> bool:
        async with tenant_transaction(self._pool, tenant_id) as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    """
                    DELETE FROM documents
                    WHERE id = %s AND tenant_id = %s
                    RETURNING id
                    """,
                    (document_id, tenant_id),
                )
                deleted = await cur.fetchone()
                return deleted is not None
