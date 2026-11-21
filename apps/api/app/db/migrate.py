from pathlib import Path

import psycopg

from app.core.config import get_settings
from app.core.logging import configure_logging, get_logger

logger = get_logger(__name__)

MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"


def run_migrations(database_admin_url: str | None = None) -> list[str]:
    """Apply pending SQL migrations idempotently in sorted filename order."""
    settings = get_settings()
    conninfo = database_admin_url or settings.database_admin_url
    sql_files = sorted(MIGRATIONS_DIR.glob("*.sql"))

    applied_now: list[str] = []

    with psycopg.connect(conninfo, autocommit=False) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    version TEXT PRIMARY KEY,
                    applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
                )
                """
            )
            cur.execute("SELECT version FROM schema_migrations")
            already_applied = {row[0] for row in cur.fetchall()}
        conn.commit()

        for sql_path in sql_files:
            version = sql_path.name
            if version in already_applied:
                logger.info("migration_skipped", version=version)
                continue

            sql_body = sql_path.read_text(encoding="utf-8")
            with conn.cursor() as cur:
                cur.execute(sql_body)
                cur.execute(
                    "INSERT INTO schema_migrations (version) VALUES (%s)",
                    (version,),
                )
            conn.commit()
            applied_now.append(version)
            logger.info("migration_applied", version=version)

    return applied_now


def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    applied = run_migrations(settings.database_admin_url)
    logger.info("migrations_complete", applied_count=len(applied), applied=applied)


if __name__ == "__main__":
    main()
