# Two databases, the asking user, and who may run a question

The Python server (`scripts/serve_api.py`, FastAPI) uses two PostgreSQL
databases. Each one has its own settings and its own login.

| | Database 1: business | Database 2: chats |
|---|---|---|
| Holds | the `tms_*` views and the rest of the TMS data | `py_sql_chat`, `py_sql_chat_turn` |
| Settings | `DATABASE_*` | `HISTORY_DATABASE_*` |
| Login used by the server | `DATABASE_READONLY_USER` (SELECT only) | `HISTORY_DATABASE_USER` (SELECT, INSERT, UPDATE on the two tables) |
| Used for | generated SQL, the full-CSV rerun, user names and roles | saving chats, listing and opening them, the monthly token count |
| Code | `database/connection.py` (`run_readonly`) | `pipeline/chat_store.py` (`ChatStore._connect`) |

Only PostgreSQL is supported, for both.

There are three separate controls. Each one is set in a different place.

---

## 1. Available views: what the chatbot may query

**File:** `metadata/schema_description.yaml`, plus
`metadata/site/attributes_schema_description.yaml` for the Arvind site.

Only the views listed here exist for the chatbot. A view that is in the
database but not in this file:

- is not in the system prompt (`claude/prompts.py` builds the prompt from it);
- fails the schema check (`pipeline/sql_semantics.py`, `check_against_schema`).
  Generated SQL that names it is not run, and is marked `HALLUCINATION`;
- cannot be downloaded again as CSV (`full_csv` runs the same check).

The other metadata files add what SQL generation needs for the listed views:

| File | What it controls |
|---|---|
| `metadata/schema_description.yaml` | views, columns, types, descriptions, primary keys, allowed values |
| `metadata/business_rules.yaml` | business rules and default filters |
| `metadata/column_hierarchy.yaml` | column order, hidden columns, row groups |
| `metadata/question_sql_pairs.yaml` | example questions and their SQL |
| `metadata/entity_gazetteer.yaml` | names the chatbot recognises in a question |
| `metadata/site/*.yaml` | the site's additions, merged at start-up (`pipeline/metadata.py`) |

**To add a view:** add it under `tables:` in `schema_description.yaml`, with
each column the chatbot may use. Add its rules to `business_rules.yaml` and
its column order to `column_hierarchy.yaml` if it needs them. Restart the
server.

**To change what a view exposes:** remove a column from its `columns:` list.
The schema check then rejects SQL that uses it.

**To remove a view:** delete its entry, and every rule, hierarchy entry and
example that names it. Restart the server.

**Rules for these files:**

- The five files directly under `metadata/` must stay byte-identical to the
  Drupal module's `metadata/` (parity checks this). Make the same change in
  Drupal, then copy the file byte for byte, so the line endings do not change.
- `metadata/site/` must stay CRLF, like the Drupal site module's copies.
- After any change, run the parity check (`docs/gotchas.md`, section 2).

**Database-level limit:** the registry decides what the chatbot may use. The
read-only login decides what the database allows. `wren_ro` can SELECT every
table, because of the database's default privileges. So the registry is the
real limit on views, and the read-only login is the limit on writes.

---

## 2. Command authorization: who may run a question

**Setting:** `CHATBOT_RUN_ROLES` in `.env`, for example
`CHATBOT_RUN_ROLES=wcms_admin,ticket_owner,administrator`.
**Code:** `pipeline/run_access.py`.

"Run" means asking a question: `POST /ask` and `POST /ask/stream`. The full
CSV (`GET /chats/<id>/turns/<n>/csv`) runs the stored SQL again, so it needs
the same permission. A run is always one read-only SELECT:

- `pipeline/safety.py` refuses anything that is not a single SELECT;
- the transaction is `READ ONLY` and has a statement timeout;
- it runs as `DATABASE_READONLY_USER`.

No role allows more than this.

How a request is checked, before any SQL or model call:

1. `user_id` must be in the request body (for `/chats`, in the query string).
   It must be a positive whole number: `12` or `"12"`. A missing id gives
   **400** `user_id_required`. Any other value gives **400** `user_id_invalid`.
   The server never uses a default user.
2. The user's roles are read from `vf_user__roles` in database 1. These are
   the Drupal roles of the TMS site, so this adds no second user list.
   `authenticated` is added for every user in `tms_user_flat`.
3. If none of the roles is in `CHATBOT_RUN_ROLES`, the response is **403**
   `run_not_allowed`. An empty `CHATBOT_RUN_ROLES` means nobody may ask.
   If the roles cannot be read, the request is refused.

Roles are cached for 60 seconds. Listing and opening your own chats needs a
valid `user_id` but no run role.

**Trust:** the server takes `user_id` as sent. It binds to 127.0.0.1 by
default. Any program on this machine can claim any user. Do not expose it
with `--host` without adding authentication in front of it.

---

## 3. Persistence identity: who writes the chats

**Settings:** `HISTORY_DATABASE_HOST`, `HISTORY_DATABASE_PORT`,
`HISTORY_DATABASE_NAME`, `HISTORY_DATABASE_USER`, `HISTORY_DATABASE_PASSWORD`.
**Code:** `ChatStore._connect` in `pipeline/chat_store.py`. This is the only
place that connects to database 2.

- None of these settings falls back to `DATABASE_*`.
- The server refuses to start (`Settings.problems()`) when:
  - the chat database is the business database;
  - `HISTORY_DATABASE_USER` is `DATABASE_USER` or `DATABASE_READONLY_USER`;
  - only one of `HISTORY_DATABASE_NAME` and `HISTORY_DATABASE_USER` is set.
- With neither set, answers still work, and chats are not saved.
- The writer login can only SELECT, INSERT and UPDATE the two tables and use
  their sequences. It cannot DELETE, TRUNCATE or create tables. Other logins
  cannot connect to the chat database.

`user_id` and `HISTORY_DATABASE_USER` are different things:

- `user_id` is the person asking. It is stored in `py_sql_chat.uid`.
- `HISTORY_DATABASE_USER` is the database account that writes the row.

**What is used, and where to see it:**

- At start-up the server prints each database, host and login. It never prints
  a password.
- `GET /health` returns `chat_database: {configured, ok, name, role}`,
  `read_only_role`, and `run_roles`.
- Passwords are left out of `repr(Settings)` and removed from logs
  (`config/logging.py`).

---

## The two chat tables

Made by `database/migrations/2026-10-19_chat_database.sql`. They have the same
columns as Drupal's `vf_sql_chat` and `vf_sql_chat_turn`.

**`py_sql_chat`:** one row per conversation.

| Column | Holds |
|---|---|
| `id` | serial key |
| `uid` | **the request's `user_id`** (bigint, ≥ 0) |
| `session_id` | the client's session id, cleaned (≤ 64 characters) |
| `title` | the first question, clipped |
| `created_at`, `updated_at` | Unix seconds |

`UNIQUE (uid, session_id)` means one user's session id never reaches another
user's chat. Every read and write filters on `uid`. In the server's memory,
conversations are also kept per (`user_id`, `session_id`).

**`py_sql_chat_turn`:** one row per question.

| Column | Holds |
|---|---|
| `chat_id` | references `py_sql_chat.id` (ON DELETE CASCADE) |
| `sequence_number` | 1, 2, 3 … within the chat |
| `question`, `generated_sql`, `llm_response` | what was asked, run and answered |
| `status`, `response_type` | outcome (`success`, `clarification`, …) |
| `llm_mode`, `llm_model`, `effective_tokens` | which model answered, and the cost |
| `step_timings`, `metadata` | JSON: timings, result shape, state. Never rows |

---

## How the connections start

- **Database 1:** `run_readonly` opens one connection per worker thread as
  `DATABASE_READONLY_USER`. Each query runs in a READ ONLY transaction, then
  rolls back. The server closes the thread's connection at the end of each
  request.
- **Database 2:** `ChatStore` opens a short connection for each operation
  (load, save, record turn, list, open) as `HISTORY_DATABASE_USER`. A failed
  write is logged, and the answer is still returned.

## Setting up a new environment

1. Copy `.env.example` to `.env`. Fill in `DATABASE_*` and
   `DATABASE_READONLY_*` for the business database.
2. Make the chat database and its login, as a superuser:

   ```
   psql -U postgres -d postgres \
        -v chat_db=wren_chatbot -v writer=wren_chat_writer \
        -v writer_password='<long random password>' \
        -f database/migrations/2026-10-19_chat_database.sql
   ```

3. Set `HISTORY_DATABASE_HOST/PORT/NAME/USER/PASSWORD` to match.
4. Set `CHATBOT_RUN_ROLES` to the Drupal roles that may ask.
5. Install the dependencies (`pip install -r requirements.txt`, which now
   includes FastAPI and uvicorn) and start the server:
   `python scripts/serve_api.py`.
6. Check `GET /health`: `ok` should be true, and `chat_database.ok` should
   be true.
7. Open the console as `http://127.0.0.1:8000/?user_id=<TMS user id>`.

The older `2026-10-16_chat_history.sql` put the same tables in the business
database. Those tables, and the chats in them, are still there. The server
no longer uses them.
