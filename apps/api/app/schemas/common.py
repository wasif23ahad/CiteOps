from typing import Annotated

from pydantic import Field

from app.domain.models import CacheTier, DocType, QueryStatus

TENANT_ID_PATTERN = r"^[a-z0-9][a-z0-9_-]{1,62}$"

TenantId = Annotated[
    str,
    Field(
        pattern=TENANT_ID_PATTERN,
        min_length=2,
        max_length=63,
        description="Tenant workspace slug (lowercase alphanumeric, '-', '_').",
        examples=["acme-corp", "globex-io"],
    ),
]

__all__ = ["CacheTier", "DocType", "QueryStatus", "TENANT_ID_PATTERN", "TenantId"]
