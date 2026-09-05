"""Create the demo database objects and the read-only benchmark role.

Idempotent: safe to re-run. Uses the owner account; this is the only module
that connects with write privileges.
"""

from __future__ import annotations

from pathlib import Path

import psycopg
from psycopg import sql as pgsql

from config.logging import get_logger
from config.settings import Settings
from database.connection import connect

HERE = Path(__file__).resolve().parent
SCHEMA_SQL = HERE / "schema.sql"
SEED_SQL = HERE / "seed.sql"

log = get_logger("database.setup")


def apply_schema_and_seed(settings: Settings) -> None:
    with connect(settings) as conn:
        with conn.cursor() as cur:
            log.info("applying schema.sql")
            cur.execute(SCHEMA_SQL.read_text(encoding="utf-8"))
            log.info("applying seed.sql")
            cur.execute(SEED_SQL.read_text(encoding="utf-8"))
        conn.commit()
    log.info("schema and seed applied")


def create_readonly_role(settings: Settings) -> None:
    """Create the SELECT-only role the benchmark executes generated SQL as."""
    if not settings.pg_readonly_password:
        raise RuntimeError(
            "DATABASE_READONLY_PASSWORD is empty. Set it in .env before setup."
        )

    role = pgsql.Identifier(settings.pg_readonly_user)
    db = pgsql.Identifier(settings.pg_database)

    with connect(settings) as conn:
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute(
                "SELECT 1 FROM pg_roles WHERE rolname = %s",
                (settings.pg_readonly_user,),
            )
            exists = cur.fetchone() is not None
            action = "ALTER" if exists else "CREATE"
            cur.execute(
                pgsql.SQL("{} ROLE {} LOGIN PASSWORD {}").format(
                    pgsql.SQL(action), role, pgsql.Literal(settings.pg_readonly_password)
                )
            )
            # SELECT only. No INSERT/UPDATE/DELETE, no DDL, no default-privilege
            # grants beyond SELECT on future tables.
            cur.execute(pgsql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(db, role))
            cur.execute(pgsql.SQL("GRANT USAGE ON SCHEMA public TO {}").format(role))
            cur.execute(
                pgsql.SQL("GRANT SELECT ON ALL TABLES IN SCHEMA public TO {}").format(role)
            )
            cur.execute(
                pgsql.SQL(
                    "ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO {}"
                ).format(role)
            )
            # Revoke anything inherited from PUBLIC that would allow writing.
            cur.execute(pgsql.SQL("REVOKE CREATE ON SCHEMA public FROM {}").format(role))
    log.info("read-only role %s ready", settings.pg_readonly_user)


def verify(settings: Settings) -> dict[str, int]:
    counts: dict[str, int] = {}
    with connect(settings) as conn:
        with conn.cursor() as cur:
            for table in ("users", "workflows", "tasks"):
                cur.execute(pgsql.SQL("SELECT count(*) FROM {}").format(pgsql.Identifier(table)))
                counts[table] = cur.fetchone()[0]
    return counts


def setup_all(settings: Settings) -> dict[str, int]:
    try:
        apply_schema_and_seed(settings)
        create_readonly_role(settings)
    except psycopg.OperationalError as exc:
        raise RuntimeError(
            f"cannot connect to PostgreSQL as '{settings.pg_user}' at "
            f"{settings.pg_host}:{settings.pg_port}/{settings.pg_database}. "
            f"Check DATABASE_* values in .env. Driver said: {exc}"
        ) from exc
    return verify(settings)
