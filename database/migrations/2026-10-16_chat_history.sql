-- Saved chats for the Python app, 2026-10-16: two tables beside Drupal's.
--
-- Python keeps its chats in the Drupal database, in tables of its own:
-- py_sql_chat and py_sql_chat_turn (CHAT_TABLE_PREFIX=py_). They are copies
-- of Drupal's vf_sql_chat and vf_sql_chat_turn -- columns, types, defaults
-- and checks taken from the live definitions -- with the names changed, so
-- the two apps never read or count each other's chats.
--
-- Two roles, both named by whoever runs this:
--   :history_role   writes the history (HISTORY_DATABASE_USER)
--   :readonly_role  runs generated SQL; must NOT read the history, or a
--                   question could read every user's questions back. This
--                   database grants that role SELECT on every new table by
--                   default, so the REVOKE at the end is required.
--
--   psql -v history_role=postgres -v readonly_role=wren_ro -f this-file

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

GRANT SELECT, INSERT, UPDATE, DELETE ON py_sql_chat, py_sql_chat_turn TO :history_role;
GRANT USAGE, SELECT ON SEQUENCE py_sql_chat_id_seq, py_sql_chat_turn_id_seq TO :history_role;

-- The read-only role's revoke, as the Drupal module's install does for its own.
REVOKE ALL ON py_sql_chat, py_sql_chat_turn FROM :readonly_role;
