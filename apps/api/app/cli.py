import asyncio
import sys

import uvicorn

from app.core.config import get_settings


def configure_event_loop_policy() -> None:
    """Psycopg 3 async requires SelectorEventLoop on Windows."""
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


def serve() -> None:
    """Start the FastAPI server with cross-platform event loop compatibility."""
    configure_event_loop_policy()
    settings = get_settings()
    uvicorn.run(
        "app.main:app",
        host=settings.api_host,
        port=settings.api_port,
        workers=1,
        loop="asyncio",
    )


if __name__ == "__main__":
    serve()
