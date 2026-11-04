-- Soft delete for saved chats, 2026-11-02.
--
-- Drupal's vf_sql_chatbot_update_9014: py_sql_chat.status, 1 active and 0
-- deleted by its owner. A deleted chat leaves the list and no longer opens;
-- its turns are kept. Existing chats stay active.
--
-- The writer already has UPDATE on py_sql_chat, which is all a delete needs,
-- so no grant changes. Run as the chat database's owner, with psql:
--
--   psql -U postgres -d wren_chatbot -f database/migrations/2026-11-02_chat_status.sql
--
-- Safe to run again.

\set ON_ERROR_STOP on

ALTER TABLE py_sql_chat ADD COLUMN IF NOT EXISTS status smallint NOT NULL DEFAULT 1;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'py_sql_chat_status_check') THEN
        ALTER TABLE py_sql_chat ADD CONSTRAINT py_sql_chat_status_check CHECK ((status >= 0));
    END IF;
END
$$;
