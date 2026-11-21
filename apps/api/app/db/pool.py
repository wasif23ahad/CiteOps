import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from pgvector.psycopg import register_vector_async
from psycopg import AsyncConnection
from psycopg_pool import AsyncConnectionPool

from app.core.config import Settings

TENANT_ID_REGEX = re.compile(r"^[a-z0-9][a-z0-9_-]{1,62}$")


def validate_tenant_id(tenant_id: str) -> str:
    """Validate tenant slug format before binding to PostgreSQL RLS session state."""
    if not TENANT_ID_REGEX.fullmatch(tenant_id):
        raise ValueError(
            "Invalid tenant_id format; expected 2-63 lowercase alphanumeric, '-' or '_' chars."
        )
    return tenant_id


async def _configure_connection(conn: AsyncConnection[Any]) -> None:
    """Register pgvector codecs on each newly established pooled connection."""
    await register_vector_async(conn)


def create_db_pool(settings: Settings, conninfo: str | None = None) -> AsyncConnectionPool:
    """Create an async PostgreSQL connection pool compatible with pgvector and Neon."""
    return AsyncConnectionPool(
        conninfo=conninfo or settings.database_url,
        min_size=settings.db_pool_min_size,
        max_size=settings.db_pool_max_size,
        open=False,
        configure=_configure_connection,
        kwargs={"autocommit": False, "prepare_threshold": 0},
    )


@asynccontextmanager
async def tenant_transaction(
    pool: AsyncConnectionPool,
    tenant_id: str,
) -> AsyncIterator[AsyncConnection[Any]]:
    """Open an ACID transaction with PostgreSQL RLS locked to `tenant_id`."""
    validated = validate_tenant_id(tenant_id)
    async with pool.connection() as conn:
        async with conn.transaction():
            await conn.execute(
                "SELECT set_config('app.current_tenant_id', %s, true)",
                (validated,),
            )
            yield conn
