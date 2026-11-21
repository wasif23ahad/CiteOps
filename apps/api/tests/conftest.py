import asyncio
import sys

# Ensure psycopg3 async compatibility on Windows test runners
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
