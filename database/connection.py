"""PostgreSQL access.

Two distinct roles are used deliberately:

* the **owner** account, only in ``database/setup.py``, to create and seed;
* a **read-only** role, for every query the benchmark executes.

``run_readonly`` never raises on SQL errors. A benchmark must record a failing
query as a data point, not crash on it, so errors come back inside QueryResult.
"""

from __future__ import annotations

import time

import psycopg

from benchmark.models import QueryResult
from config.settings import Settings


def _dsn(settings: Settings, readonly: bool) -> dict:
    user = settings.pg_readonly_user if readonly else settings.pg_user
    password = settings.pg_readonly_password if readonly else settings.pg_password
    return {
        "host": settings.pg_host,
        "port": settings.pg_port,
        "dbname": settings.pg_database,
        "user": user,
        "password": password,
        "connect_timeout": 10,
    }


def connect(settings: Settings, readonly: bool = False) -> psycopg.Connection:
    """Open a connection. Caller owns closing it."""
    return psycopg.connect(**_dsn(settings, readonly))


def run_readonly(
    settings: Settings,
    sql: str,
    timeout_ms: int | None = None,
    readonly_role: bool = True,
) -> QueryResult:
    """Execute one statement under a READ ONLY transaction and a hard timeout.

    Defence in depth alongside benchmark.safety: even if the safety gate were
    bypassed, the role lacks write grants and the transaction refuses writes.
    """
    timeout = timeout_ms or settings.statement_timeout_ms
    started = time.perf_counter()
    try:
        with psycopg.connect(**_dsn(settings, readonly_role)) as conn:
            with conn.cursor() as cur:
                cur.execute("SET TRANSACTION READ ONLY")
                cur.execute(f"SET LOCAL statement_timeout = {int(timeout)}")
                cur.execute(sql)
                columns = [d.name for d in cur.description] if cur.description else []
                rows = [tuple(r) for r in cur.fetchall()] if cur.description else []
            conn.rollback()
        return QueryResult(
            columns=columns,
            rows=rows,
            duration_ms=(time.perf_counter() - started) * 1000,
        )
    except psycopg.Error as exc:
        return QueryResult(
            columns=[],
            rows=[],
            duration_ms=(time.perf_counter() - started) * 1000,
            error=str(exc).strip(),
            sqlstate=getattr(exc, "sqlstate", None),
        )
    except Exception as exc:  # driver-level problems, e.g. bad DSN
        return QueryResult(
            columns=[],
            rows=[],
            duration_ms=(time.perf_counter() - started) * 1000,
            error=f"{type(exc).__name__}: {exc}",
        )
