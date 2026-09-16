"""PostgreSQL access.

Two distinct roles are used deliberately:

* the **owner** account, only in ``database/setup.py``, to create and seed;
* a **read-only** role, for every query the benchmark executes.

``run_readonly`` never raises on SQL errors. A benchmark must record a failing
query as a data point, not crash on it, so errors come back inside QueryResult.
"""

from __future__ import annotations

import threading
import time

import psycopg

from pipeline.models import QueryResult
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


# One read-only connection per thread, kept open between queries.
#
# Opening one costs about 110ms -- measured with `SELECT 1`, which is almost
# entirely connect and TLS/auth handshake rather than query time -- and an
# answer runs one or two statements, so this was up to 220ms of every turn
# spent saying hello. Per-thread rather than a shared pool because psycopg
# connections are not thread-safe and the HTTP server is threaded; a thread
# gets its own or it gets nothing.
#
# The connection is still used exactly as before: READ ONLY transaction, a
# statement timeout, and a rollback after every query. Reuse changes how
# often we connect, not what a query is allowed to do.
_LOCAL = threading.local()


def _reusable(settings: Settings, readonly: bool) -> psycopg.Connection | None:
    """This thread's connection, opening or reopening it as needed.

    Returns None if the connection cannot be established, so the caller can
    report the error the same way it always did.
    """
    conn = getattr(_LOCAL, "conn", None)
    key = (settings.pg_host, settings.pg_port, settings.pg_database, readonly)
    if conn is not None and getattr(_LOCAL, "key", None) == key:
        if not conn.closed:
            return conn
    close_thread_connection()
    conn = psycopg.connect(**_dsn(settings, readonly))
    _LOCAL.conn, _LOCAL.key = conn, key
    return conn


def close_thread_connection() -> None:
    """Drop this thread's pooled connection, if it has one."""
    conn = getattr(_LOCAL, "conn", None)
    _LOCAL.conn = _LOCAL.key = None
    if conn is not None and not conn.closed:
        try:
            conn.close()
        except Exception:
            pass


def run_readonly(
    settings: Settings,
    sql: str,
    timeout_ms: int | None = None,
    readonly_role: bool = True,
) -> QueryResult:
    """Execute one statement under a READ ONLY transaction and a hard timeout.

    Defence in depth alongside pipeline.safety: even if the safety gate were
    bypassed, the role lacks write grants and the transaction refuses writes.
    """
    timeout = timeout_ms or settings.statement_timeout_ms
    started = time.perf_counter()
    try:
        conn = _reusable(settings, readonly_role)
        try:
            with conn.cursor() as cur:
                cur.execute("SET TRANSACTION READ ONLY")
                cur.execute(f"SET LOCAL statement_timeout = {int(timeout)}")
                cur.execute(sql)
                columns = [d.name for d in cur.description] if cur.description else []
                rows = [tuple(r) for r in cur.fetchall()] if cur.description else []
        finally:
            # Always, on the success and the failure path alike. The
            # connection outlives the query now, so leaving a transaction
            # open would poison every later query on this thread -- and
            # `SET LOCAL` only lasts as long as the transaction, which is
            # what keeps the statement timeout honest per query.
            try:
                conn.rollback()
            except psycopg.Error:
                # The connection itself is gone. Drop it rather than let the
                # rollback failure mask whatever really went wrong.
                close_thread_connection()
        return QueryResult(
            columns=columns,
            rows=rows,
            duration_ms=(time.perf_counter() - started) * 1000,
        )
    except psycopg.Error as exc:
        # A reused connection must never carry a fault into the next query,
        # and there is no cheap way to tell "bad SQL" from "broken socket"
        # here. Dropping it costs one reconnect; keeping a poisoned one costs
        # every subsequent answer on this thread.
        close_thread_connection()
        return QueryResult(
            columns=[],
            rows=[],
            duration_ms=(time.perf_counter() - started) * 1000,
            error=str(exc).strip(),
            sqlstate=getattr(exc, "sqlstate", None),
        )
    except Exception as exc:  # driver-level problems, e.g. bad DSN
        close_thread_connection()
        return QueryResult(
            columns=[],
            rows=[],
            duration_ms=(time.perf_counter() - started) * 1000,
            error=f"{type(exc).__name__}: {exc}",
        )
