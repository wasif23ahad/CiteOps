"""Idempotent demo corpus seeder for CiteOps (`acme-corp` and `globex-io`)."""

from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass
from pathlib import Path

import httpx
from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parent.parent
DEMO_DOCS_DIR = Path(__file__).resolve().parent / "demo_docs"


@dataclass(frozen=True)
class SeedDocument:
    tenant_id: str
    relative_path: str
    doc_title: str
    doc_type: str
    version: str


SEED_MANIFEST: tuple[SeedDocument, ...] = (
    SeedDocument(
        tenant_id="acme-corp",
        relative_path="acme-corp/webhook_error_reference_v2.4.1.md",
        doc_title="Webhook Integration & Error Reference",
        doc_type="api_docs",
        version="v2.4.1",
    ),
    SeedDocument(
        tenant_id="acme-corp",
        relative_path="acme-corp/enterprise_sla_contract_v3.2.md",
        doc_title="CloudPulse Enterprise SLA Contract",
        doc_type="sla_contract",
        version="v3.2",
    ),
    SeedDocument(
        tenant_id="acme-corp",
        relative_path="acme-corp/soc2_iso27001_security_policy_v2.1.md",
        doc_title="SOC 2 Type II & ISO-27001 Security Compliance Policy",
        doc_type="security_policy",
        version="v2.1",
    ),
    SeedDocument(
        tenant_id="acme-corp",
        relative_path="acme-corp/production_rollback_runbook_v2.4.md",
        doc_title="Production Rollback Runbook: Webhook SDK v2.4.1",
        doc_type="runbook",
        version="v2.4",
    ),
    SeedDocument(
        tenant_id="globex-io",
        relative_path="globex-io/globex_custom_sla_v1.0.md",
        doc_title="Globex IO Confidential Sovereign SLA Addendum",
        doc_type="sla_contract",
        version="v1.0",
    ),
    SeedDocument(
        tenant_id="globex-io",
        relative_path="globex-io/globex_internal_runbook_v1.2.md",
        doc_title="Globex IO Private Webhook Relay Rotation Runbook",
        doc_type="runbook",
        version="v1.2",
    ),
)


def seed_all(api_url: str, internal_api_key: str) -> int:
    headers: dict[str, str] = {}
    if internal_api_key:
        headers["X-Internal-API-Key"] = internal_api_key

    endpoint = f"{api_url.rstrip('/')}/v1/ingest"
    print(f"Seeding {len(SEED_MANIFEST)} documents into {endpoint}...\n")
    print(
        f"{'TENANT':<12} | {'STATUS':<18} | {'PAGES':>5} | {'CHUNKS':>6} | "
        f"{'VER':>3} | {'MS':>6} | DOCUMENT"
    )
    print("-" * 96)

    failures = 0
    with httpx.Client(timeout=120.0) as client:
        for item in SEED_MANIFEST:
            file_path = DEMO_DOCS_DIR / item.relative_path
            if not file_path.exists():
                print(f"ERROR: Missing demo file: {file_path}", file=sys.stderr)
                failures += 1
                continue

            with file_path.open("rb") as fh:
                resp = client.post(
                    endpoint,
                    headers=headers,
                    data={
                        "tenant_id": item.tenant_id,
                        "doc_type": item.doc_type,
                        "version": item.version,
                        "doc_title": item.doc_title,
                    },
                    files={"file": (file_path.name, fh, "text/markdown")},
                )

            if resp.status_code != 200:
                print(
                    f"{item.tenant_id:<12} | FAILED ({resp.status_code}) | {resp.text}",
                    file=sys.stderr,
                )
                failures += 1
                continue

            body = resp.json()
            print(
                f"{body['tenant_id']:<12} | {body['status']:<18} | "
                f"{body['page_count']:>5} | {body['chunk_count']:>6} | "
                f"v{body['corpus_version']:>2} | {body['latency_ms']:>6} | {body['doc_title']}"
            )

    print("-" * 96)
    if failures:
        print(f"Completed with {failures} failure(s).", file=sys.stderr)
        return 1
    print("Seed completed cleanly.")
    return 0


def main() -> None:
    load_dotenv(ROOT_DIR / ".env")

    parser = argparse.ArgumentParser(description="Seed CiteOps demo tenants via /v1/ingest.")
    parser.add_argument(
        "--api-url",
        default=os.getenv("CITEOPS_API_URL", "http://localhost:8000"),
        help="CiteOps FastAPI base URL (default: http://localhost:8000)",
    )
    parser.add_argument(
        "--api-key",
        default=os.getenv("CITEOPS_INTERNAL_API_KEY", ""),
        help="X-Internal-API-Key header value (defaults to CITEOPS_INTERNAL_API_KEY from .env)",
    )
    args = parser.parse_args()
    raise SystemExit(seed_all(args.api_url, args.api_key))


if __name__ == "__main__":
    main()
