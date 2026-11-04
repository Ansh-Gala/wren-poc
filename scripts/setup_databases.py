"""Set up PostgreSQL for the chatbot, from .env.

    python scripts/setup_databases.py --dry-run   # do everything, then roll back
    python scripts/setup_databases.py

Connects as the owner login (DATABASE_USER / DATABASE_PASSWORD), which must be
allowed to create logins and databases. Safe to run again: what exists is
kept, and a login that exists keeps its password (wren_ro is shared with the
Drupal site).

1. Business database: the read-only login, with SELECT on exactly the columns
   the product's metadata describes (METADATA_DIR), so vpp_users.password is
   never readable.
2. Chat database: created if missing, with its writer login and the two
   <CHAT_TABLE_PREFIX>sql_chat tables.

Each database's changes are one transaction.
"""

from __future__ import annotations

import argparse
import os
import sys

import _bootstrap  # noqa: F401

import psycopg
from dotenv import dotenv_values
from psycopg.sql import SQL, Identifier as Id, Literal

from config.settings import ROOT, load_settings

REQUIRED = (
    "DATABASE_HOST", "DATABASE_PORT", "DATABASE_NAME",
    "DATABASE_USER", "DATABASE_PASSWORD",
    "DATABASE_READONLY_USER", "DATABASE_READONLY_PASSWORD",
    "HISTORY_DATABASE_HOST", "HISTORY_DATABASE_PORT", "HISTORY_DATABASE_NAME",
    "HISTORY_DATABASE_USER", "HISTORY_DATABASE_PASSWORD", "CHAT_TABLE_PREFIX",
)

BUSINESS_SQL = """
GRANT CONNECT ON DATABASE {db} TO {login};
GRANT USAGE ON SCHEMA {schema} TO {login};
"""

# The tables of database/migrations/2026-10-19 and 2026-11-02. The writer may
# read, add and change rows, and nothing else: the app never deletes.
CHAT_SQL = """
REVOKE ALL ON DATABASE {db} FROM PUBLIC;
GRANT CONNECT ON DATABASE {db} TO {writer};
REVOKE ALL ON SCHEMA public FROM PUBLIC;
GRANT USAGE ON SCHEMA public TO {writer};

CREATE TABLE IF NOT EXISTS {chats} (
    id          serial       PRIMARY KEY,
    uid         bigint       NOT NULL DEFAULT 0 CHECK (uid >= 0),
    session_id  varchar(64)  NOT NULL DEFAULT '',
    title       varchar(255) NOT NULL DEFAULT '',
    created_at  bigint       NOT NULL DEFAULT 0 CHECK (created_at >= 0),
    updated_at  bigint       NOT NULL DEFAULT 0 CHECK (updated_at >= 0),
    status      smallint     NOT NULL DEFAULT 1 CHECK (status >= 0),
    UNIQUE (uid, session_id)
);
-- A table made before 2026-11-02 has no status column.
ALTER TABLE {chats} ADD COLUMN IF NOT EXISTS
    status smallint NOT NULL DEFAULT 1 CHECK (status >= 0);

CREATE TABLE IF NOT EXISTS {turns} (
    id               serial      PRIMARY KEY,
    chat_id          bigint      NOT NULL REFERENCES {chats} (id) ON DELETE CASCADE,
    sequence_number  bigint      NOT NULL DEFAULT 0 CHECK (sequence_number >= 0),
    question         text,
    generated_sql    text,
    status           varchar(32) NOT NULL DEFAULT '',
    response_type    varchar(20) NOT NULL DEFAULT '',
    llm_response     text,
    step_timings     json,
    metadata         json,
    created_at       bigint      NOT NULL DEFAULT 0 CHECK (created_at >= 0),
    llm_mode         varchar(32),
    llm_model        varchar(64),
    effective_tokens bigint      NOT NULL DEFAULT 0 CHECK (effective_tokens >= 0),
    UNIQUE (chat_id, sequence_number)
);

GRANT SELECT, INSERT, UPDATE ON {chats}, {turns} TO {writer};
GRANT USAGE ON SEQUENCE {chats_seq}, {turns_seq} TO {writer};
"""


def check_env() -> None:
    """Stop before connecting if a key is missing. A real environment
    variable wins over .env, as in config/settings.py."""
    values = {**dotenv_values(ROOT / ".env"), **{k: v for k, v in os.environ.items() if v}}
    missing = [key for key in REQUIRED if not (values.get(key) or "").strip()]
    if missing:
        sys.exit("Nothing was changed. Missing in .env: " + ", ".join(missing))


def owner(settings, host, port, dbname, autocommit=False) -> psycopg.Connection:
    return psycopg.connect(host=host, port=port, dbname=dbname, user=settings.pg_user,
                           password=settings.pg_password, autocommit=autocommit)


def ensure_login(conn, name: str, password: str) -> str:
    if conn.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (name,)).fetchone():
        return f"login {name}: exists, password not changed"
    conn.execute(SQL("CREATE ROLE {} LOGIN PASSWORD {} "
                     "NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT")
                 .format(Id(name), Literal(password)))
    return f"login {name}: created"


def setup_business(settings, dry_run: bool) -> list[str]:
    from pipeline import metadata

    metadata.enable_site_metadata()
    doc = metadata.schema()
    schema = doc.get("schema") or "public"
    described = {t: list((spec or {}).get("columns") or {})
                 for t, spec in (doc.get("tables") or {}).items()}
    login, db = settings.pg_readonly_user, settings.pg_database

    with owner(settings, settings.pg_host, settings.pg_port, db) as conn, conn.transaction():
        log = [ensure_login(conn, login, settings.pg_readonly_password)]
        conn.execute(SQL(BUSINESS_SQL).format(db=Id(db), schema=Id(schema), login=Id(login)))
        actual: dict[str, set[str]] = {}
        for table, column in conn.execute("SELECT table_name, column_name FROM "
                                          "information_schema.columns WHERE table_schema = %s",
                                          (schema,)):
            actual.setdefault(table, set()).add(column)
        granted = 0
        for table, columns in described.items():
            present = [c for c in columns if c in actual.get(table, ())]
            log += [f"  skipped {table}.{c}: not in {db}"
                    for c in columns if table in actual and c not in actual[table]]
            if not present:
                log.append(f"  skipped {table}: not in {db}")
                continue
            conn.execute(SQL("GRANT SELECT ({}) ON {}.{} TO {}").format(
                SQL(", ").join(map(Id, present)), Id(schema), Id(table), Id(login)))
            granted += 1
        log.append(f"read access for {login}: {granted} of {len(described)} tables, "
                   "described columns only")
        if dry_run:
            raise psycopg.Rollback()
    return log


def setup_chat(settings, dry_run: bool) -> list[str]:
    db, writer, prefix = (settings.history_db_name, settings.history_db_user,
                          settings.chat_table_prefix)
    host, port = settings.history_db_host, settings.history_db_port

    # CREATE DATABASE cannot run inside a transaction, so it runs first.
    with owner(settings, host, port, "postgres", autocommit=True) as conn:
        if not conn.execute("SELECT 1 FROM pg_database WHERE datname = %s", (db,)).fetchone():
            if dry_run:
                return [f"database {db}: would be created"]
            conn.execute(SQL("CREATE DATABASE {}").format(Id(db)))
    log = [f"database {db}: ready"]

    chats, turns = f"{prefix}sql_chat", f"{prefix}sql_chat_turn"
    with owner(settings, host, port, db) as conn, conn.transaction():
        log.append(ensure_login(conn, writer, settings.history_db_password))
        conn.execute(SQL(CHAT_SQL).format(
            db=Id(db), writer=Id(writer), chats=Id(chats), turns=Id(turns),
            chats_seq=Id(f"{chats}_id_seq"), turns_seq=Id(f"{turns}_id_seq")))
        log.append(f"tables {chats}, {turns}: ready, written by {writer}")
        if dry_run:
            raise psycopg.Rollback()
    return log


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true", help="do everything, then roll back")
    args = ap.parse_args()

    check_env()
    settings = load_settings()
    problems = settings.problems()
    if settings.pg_readonly_user == settings.pg_user:
        problems.append("DATABASE_READONLY_USER must not be DATABASE_USER.")
    if problems:
        sys.exit("Nothing was changed.\n" + "\n".join(problems))

    for title, step in (("Business database", setup_business), ("Chat database", setup_chat)):
        print(f"{title}:")
        try:
            for line in step(settings, args.dry_run):
                print(f"  {line}")
        except psycopg.Error as exc:
            sys.exit(f"  FAILED, this step was rolled back: {exc}")
    print("Done" + (" (dry run: everything rolled back)." if args.dry_run else "."))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
