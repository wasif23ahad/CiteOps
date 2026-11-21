import asyncio
import sys

import uvicorn

from app.core.config import get_settings


def serve() -> None:
    """Start FastAPI with SelectorEventLoop on Windows for psycopg 3 async compatibility."""
    settings = get_settings()
    config = uvicorn.Config(
        "app.main:app",
        host=settings.api_host,
        port=settings.api_port,
        workers=1,
        loop="asyncio",
    )
    server = uvicorn.Server(config)

    if sys.platform == "win32":
        asyncio.run(server.serve(), loop_factory=asyncio.SelectorEventLoop)
    else:
        asyncio.run(server.serve())


if __name__ == "__main__":
    serve()
