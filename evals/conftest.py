from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

import pytest

ROOT_DIR = Path(__file__).resolve().parent.parent
API_DIR = ROOT_DIR / "apps" / "api"

if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))
if str(API_DIR) not in sys.path:
    sys.path.insert(0, str(API_DIR))

os.environ.setdefault("DEEPEVAL_TELEMETRY_OPT_OUT", "YES")

# Ensure psycopg3 async compatibility on Windows pytest runners
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--suite",
        action="store",
        default=os.getenv("EVAL_SUITE", "smoke"),
        choices=("smoke", "full"),
        help="Golden evaluation suite size: 'smoke' (12 stratified Qs) or 'full' (50 Qs).",
    )
    parser.addoption(
        "--delay-seconds",
        action="store",
        type=float,
        default=float(os.getenv("EVAL_DELAY_SECONDS", "1.0")),
        help="Minimum pacing delay between judge/LLM requests for free-tier RPM safety.",
    )


@pytest.fixture(scope="session")
def eval_suite(request: pytest.FixtureRequest) -> str:
    return str(request.config.getoption("--suite"))


@pytest.fixture(scope="session")
def eval_delay_seconds(request: pytest.FixtureRequest) -> float:
    return float(request.config.getoption("--delay-seconds"))
