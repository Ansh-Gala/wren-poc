-- The chat database (database 2), 2026-10-19.
--
-- Saved chats move out of the business database into a database of their
-- own, written by a login that can do nothing else. The two tables are the
-- ones 2026-10-16_chat_history.sql made beside Drupal's: py_sql_chat and
-- py_sql_chat_turn, copies of Drupal's vf_sql_chat and vf_sql_chat_turn.
-- py_sql_chat.uid holds the request's user_id.
--
-- Run as a superuser (or a role with CREATEDB and CREATEROLE), with psql:
--
--   psql -U postgres -d postgres \
--        -v chat_db=wren_chatbot -v writer=wren_chat_writer \
--        -v writer_password='<a long random password>' \
--        -f database/migrations/2026-10-19_chat_database.sql
--
-- Then set HISTORY_DATABASE_NAME, HISTORY_DATABASE_USER and
-- HISTORY_DATABASE_PASSWORD in .env to the same three values.
--
-- The writer gets SELECT, INSERT and UPDATE on the two tables and their
-- sequences' USAGE, and nothing else: no DELETE (the app never deletes), no
-- DDL, no CONNECT to the business database. Nobody else may connect here.

\set ON_ERROR_STOP on

CREATE ROLE :"writer" LOGIN PASSWORD :'writer_password'
    NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT;
CREATE DATABASE :"chat_db";
REVOKE ALL ON DATABASE :"chat_db" FROM PUBLIC;
GRANT CONNECT ON DATABASE :"chat_db" TO :"writer";

\connect :"chat_db"

REVOKE ALL ON SCHEMA public FROM PUBLIC;
GRANT USAGE ON SCHEMA public TO :"writer";

CREATE TABLE py_sql_chat (
    id          serial                 NOT NULL,
    uid         bigint                 NOT NULL DEFAULT 0,
    session_id  character varying(64)  NOT NULL DEFAULT ''::character varying,
    title       character varying(255) NOT NULL DEFAULT ''::character varying,
    created_at  bigint                 NOT NULL DEFAULT 0,
    updated_at  bigint                 NOT NULL DEFAULT 0,
    CONSTRAINT py_sql_chat____pkey PRIMARY KEY (id),
    CONSTRAINT py_sql_chat__sql_chat_uid_session__key UNIQUE (uid, session_id),
    CONSTRAINT py_sql_chat_created_at_check CHECK ((created_at >= 0)),
    CONSTRAINT py_sql_chat_id_check CHECK ((id >= 0)),
    CONSTRAINT py_sql_chat_uid_check CHECK ((uid >= 0)),
    CONSTRAINT py_sql_chat_updated_at_check CHECK ((updated_at >= 0))
);

CREATE TABLE py_sql_chat_turn (
    id               serial                NOT NULL,
    chat_id          bigint                NOT NULL DEFAULT 0,
    sequence_number  bigint                NOT NULL DEFAULT 0,
    question         text,
    generated_sql    text,
    status           character varying(32) NOT NULL DEFAULT ''::character varying,
    response_type    character varying(20) NOT NULL DEFAULT ''::character varying,
    llm_response     text,
    step_timings     json,
    metadata         json,
    created_at       bigint                NOT NULL DEFAULT 0,
    llm_mode         character varying(32),
    llm_model        character varying(64),
    effective_tokens bigint                NOT NULL DEFAULT 0,
    CONSTRAINT py_sql_chat_turn____pkey PRIMARY KEY (id),
    CONSTRAINT py_sql_chat_turn__sql_chat_turn_chat_sequence__key UNIQUE (chat_id, sequence_number),
    CONSTRAINT py_sql_chat_turn_chat_id_fk FOREIGN KEY (chat_id) REFERENCES py_sql_chat(id) ON DELETE CASCADE,
    CONSTRAINT py_sql_chat_turn_chat_id_check CHECK ((chat_id >= 0)),
    CONSTRAINT py_sql_chat_turn_created_at_check CHECK ((created_at >= 0)),
    CONSTRAINT py_sql_chat_turn_effective_tokens_check CHECK ((effective_tokens >= 0)),
    CONSTRAINT py_sql_chat_turn_id_check CHECK ((id >= 0)),
    CONSTRAINT py_sql_chat_turn_sequence_number_check CHECK ((sequence_number >= 0))
);

GRANT SELECT, INSERT, UPDATE ON py_sql_chat, py_sql_chat_turn TO :"writer";
GRANT USAGE ON SEQUENCE py_sql_chat_id_seq, py_sql_chat_turn_id_seq TO :"writer";
