from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

DATASET_PATH = Path(__file__).resolve().parent / "datasets" / "golden_50.jsonl"


@dataclass(frozen=True, slots=True)
class ExpectedSource:
    doc_title: str
    page_number: int | None = None


@dataclass(frozen=True, slots=True)
class GoldenCase:
    id: str
    suite: Literal["smoke", "full"]
    category: Literal["exact_code", "compliance_sla", "multi_hop", "abstention", "cross_tenant"]
    tenant_id: str
    doc_types: list[str] | None
    query: str
    expected_status: Literal["answered", "insufficient_evidence"]
    expected_answer: str
    expected_sources: tuple[ExpectedSource, ...]
    expected_keywords: tuple[str, ...]
    forbidden_substrings: tuple[str, ...]


def load_golden_dataset(
    *,
    suite: Literal["smoke", "full"] = "full",
    path: Path = DATASET_PATH,
) -> list[GoldenCase]:
    cases: list[GoldenCase] = []
    with path.open("r", encoding="utf-8") as fh:
        for line_no, raw in enumerate(fh, start=1):
            stripped = raw.strip()
            if not stripped:
                continue
            item = json.loads(stripped)
            case = GoldenCase(
                id=str(item["id"]),
                suite=item["suite"],
                category=item["category"],
                tenant_id=str(item["tenant_id"]),
                doc_types=item.get("doc_types"),
                query=str(item["query"]),
                expected_status=item["expected_status"],
                expected_answer=str(item["expected_answer"]),
                expected_sources=tuple(
                    ExpectedSource(
                        doc_title=str(s["doc_title"]),
                        page_number=s.get("page_number"),
                    )
                    for s in item.get("expected_sources", [])
                ),
                expected_keywords=tuple(item.get("expected_keywords", [])),
                forbidden_substrings=tuple(item.get("forbidden_substrings", [])),
            )
            if suite == "full" or case.suite == "smoke":
                cases.append(case)
            elif suite not in ("smoke", "full"):
                raise ValueError(f"Invalid suite '{suite}' at line {line_no}")
    return cases
