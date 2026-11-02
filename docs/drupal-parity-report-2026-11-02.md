# Drupal vs Python: feature parity report

Date: 2 November 2026
Baseline: Drupal `vf_sql_chatbot` (branch `feat/drupal-11-chatbot-compat`, last commit `c3232cba8`, 29 Oct)
Checked: Python `wren-poc` (branch `develop`, last commit `4b4c808`, 2 Nov)
Out of scope: PII aliasing (Python only, on purpose) and the Python console UI.

No code was changed for this report.

---

## 0. Update: fixed later on 2 November

These items from section 4 are now done in Python. They are not committed.

| Item | Now | Where |
|---|---|---|
| Soft delete | ✅ `py_sql_chat.status`; `DELETE /chats/{id}` (200 `{"deleted": true}` / 404 "No such chat."); `status = 1` on list, count, open and CSV | `pipeline/chat_store.py`, `scripts/serve_api.py`, `database/migrations/2026-11-02_chat_status.sql` |
| 60-day chat list | ✅ `updated_at >= now − 60 days` on list and count (`LIST_DAYS = 60`) | `pipeline/chat_store.py` |
| CSV Colour column | ✅ "Colour" first, colour name per row, when the answer has an initiative id and no colour column | `scripts/serve_api.py` `csv_colour_names` |
| Row value format | ✅ Integers and booleans stay native; every other value is PostgreSQL's own text, as PDO gives it (`"12.50"`, `"2026-10-01 12:00:00.12"`, `"3 days 04:00:00"`, `"{a,b}"`). Checked against `::text` on the live DB for 66 cases. `QueryResult` now carries each column's type name. Same text in the CSV. | `pipeline/evaluator.py` `pg_text`, `database/connection.py` |
| Working state expiry | ✅ State starts over after 1 hour idle; turns and debug log kept | `scripts/serve_api.py` `expire_if_idle` |
| OpenAI timeout and retries | ✅ 500 s (`CLAUDE_TIMEOUT_SECONDS`), no retries | `llm_api/openai_provider.py` |
| CLI pool second call | ✅ A pool timeout is now a timed-out answer, never a second call. The pool waits `CLAUDE_TIMEOUT_SECONDS` (500 s), as Drupal does, not 90 s. | `llm_api/cli_pool.py`, `llm_api/cli_provider.py` |
| Blocked users | ✅ `vf_users_field_data.status = 1` is needed to run | `pipeline/run_access.py` |
| `ValueError → 400` | ✅ Only `BadRequest` ("question is required") is a 400. Any other error is a 500 with the safe text. | `scripts/serve_api.py` |
| Old overlay `.env.example` | ✅ Removed. Production now takes develop's `.env.example`, which has `CHATBOT_RUN_ROLES` and the chat database. | `promotion/overlay/.env.example`, `docs/branching.md` |

**One step left:** the local chat database does not have the `status` column yet. Run the migration as the chat database owner (see its header) before you start the server, or the chat list fails.

Checks after the change: the offline parity check still holds (prompt md5 `cccaf101…`). The Python tests pass, except for old failures that were there before: the retired demo database tests, `test_stream_endpoint.py` (it uses the old `Handler` class), and the `column_hierarchy.yaml` check.

The rows in section 3 below show the state **before** these fixes.

---

## 1. Short answer

- **The prompt the model sees is byte-identical.** This is true with and without the site overlay.
- **All metadata files are byte-identical.** This covers the six shared files and the three site overlay files.
- **The question → SQL → answer pipeline matches.** This covers the turn steps, the repair, the follow-ups, the context, charts, links, labels, row colour, the 200-row cut and the error text.
- **Three Drupal features from the last week are missing in Python:**
  1. Soft-delete a chat (`5e318177b`). **The React page already calls this.**
  2. List only chats used in the last 60 days (`c3232cba8`).
  3. "Colour" column in the full CSV download (`2cbdd7255`).
- **Some smaller things differ.** These are: the format of row values, where the working state lives, the step timings, some debug fields, and some config and access details. They are listed in section 4.

Rows in the section 3 tables:

| Result | Rows |
|---|---|
| ✅ Same (identical logic, output or bytes) | 61 |
| ⚠️ Present but different | 38 |
| ❌ Missing in Python | 11 |
| ➕ Python only | 8 |

Some ❌ rows are the same feature seen in two places. For example, DELETE chat is listed under both storage and endpoints.

Legend: ✅ same · ⚠️ different · ❌ missing in Python · ➕ only in Python

---

## 2. How this was checked

1. **md5 of each metadata file on both sides**, raw bytes and with CR removed.
2. **The offline parity harness** (`tests/parity/generate_expected.py` + `check.php`). Every layer passed at 100%:

   | Layer | Cases | Result |
   |---|---|---|
   | system prompt, user prompt, repair prompt | 1 + 1 + 3 | identical |
   | SQL state reader (tables, filters, grouping, sorting, limit, intent) | 1014 | 100% (filter_strings 99.6%, within its bar) |
   | similarity (difflib, Damerau-Levenshtein) | 9460 | 100% |
   | typo repair of the question | 436 | 100% |
   | context decision, context, state | 506 | 100% |
   | follow-up explore / with result / clarification | 1482 / 2470 / 15 | 100% |
   | column order, hidden columns, grouping | 12 | 100% |
   | initiative colour | 24 | 100% |
   | signed-in user block | 6 | 100% |
   | safety gate | 1043 | 100% |
   | schema check + SQL constructs | 1014 + 118 | 100% |
   | response parser | 1481 | 100% |
   | streaming partial-SQL scanner | 8974 | 100% |

   System prompt: 51,076 bytes, md5 `cccaf101a6312c2e2943427b37fde5d7` on both sides.

3. **A prompt built with the site overlay on.** Drupal used its hooks from `vf_arvind_retail_chatbot`. Python used `metadata/site/`. Both gave 52,734 bytes, md5 `a197959630bb474c513d887670e3dec3`.
4. **Code read side by side** for every part that parity does not cover: storage, the turn runner, endpoints, CSV, links, charts, config, providers and access.
5. **A check of every Drupal module commit since 5 October** for a matching Python commit.

---

## 3. Full feature list

### 3.1 Metadata

| Feature | Status | Note |
|---|---|---|
| `business_rules.yaml` | ✅ | byte-identical |
| `schema_description.yaml` | ✅ | byte-identical |
| `question_sql_pairs.yaml` | ✅ | byte-identical |
| `column_hierarchy.yaml` | ✅ | byte-identical |
| `product.yaml` | ✅ | byte-identical |
| `product.schema.json` | ✅ | byte-identical |
| Site overlay: attribute table schema, rules, hierarchy | ✅ | Python `metadata/site/*.yaml` = the files in Drupal's `vf_arvind_retail_chatbot` module (same md5) |
| Merge order (base first, site appended) | ✅ | |
| product.yaml shape + meaning check on load | ✅ | same checks and same wording |
| Product overlay hook (`hook_..._product_alter`) | ⚠️ | Drupal has the hook. Python has no equivalent. No module uses it today, so the output is the same. |
| When a metadata edit takes effect | ⚠️ | Drupal: on the next question. Python: only after a restart (cached). |
| Bad product.yaml | ⚠️ | Drupal fails on each request. Python will not start. |
| `build_schema_description.py` generator | ➕ | Python only. **Its output is now stale.** If you run it, it adds `tms_initiative_attributes_flat` back into the common file and breaks byte parity. Do not run it until that table is removed from its `TABLES` list. |

### 3.2 Prompt and context

| Feature | Status | Note |
|---|---|---|
| System prompt (schema + rules + all example pairs) | ✅ | md5 identical, base and with overlay |
| User prompt | ✅ | |
| Repair prompt (one retry after a DB error) | ✅ | |
| Signed-in user block (id, name, departments, "my/me") | ✅ | |
| Example pairs: all inlined, no per-question picking | ✅ | the same on both sides |
| Question typo repair (Normalizer vocabulary) | ✅ | |
| Last-10 questions window + recap, rebuilt from saved turns | ✅ | One edge: when saving is off, Python keeps an in-memory window and Drupal sends an empty one. |
| `context_reset` marker | ✅ | |
| Effort level, model, CLI flags, 4000-token reply cap, 1-hour prompt cache | ✅ | |
| Lean prompt | ⚠️ | Drupal has only lean. Python's code default is the MCP prompt. `.env` sets `CLI_LEAN=true`, so live use is the same. |

### 3.3 Follow-ups and filters

| Feature | Status | Note |
|---|---|---|
| Classify a turn as new or follow-up | ✅ | parity 506/506 |
| Carry filters, subject and grouping into the next turn | ✅ | |
| Clarification question and its resolve | ✅ | |
| Follow-up suggestions (explore / drill) | ✅ | parity 3952/3952 |
| Context pills, drop a pill, dropped filters | ✅ | same sha256 ref |
| Ordinal pick, resume | ✅ | |
| Subject read from `col = value` | ⚠️ | Drupal accepts any value, so a join like `t.id = i.id` can become the "subject". Python accepts only a quoted string or a number. **Here Python is stricter and better.** |
| Text clip at 160 / 320 | ⚠️ | Drupal counts bytes and Python counts characters. Only non-ASCII text is affected. |
| Working state expiry | ⚠️ | Drupal: key-value store, **cleared after 1 hour idle**. Python: in memory, **never expires, lost on restart**. A follow-up after 2 hours keeps old filters in Python but starts fresh in Drupal. |

### 3.4 Turn pipeline

| Feature | Status | Note |
|---|---|---|
| Step order: normalise → resume → classify → context → LLM → parse → schema check → safety gate → grounding → run → repair → chart → state → follow-up | ✅ | |
| One repair retry on a DB error, re-gated, tokens added | ✅ | |
| Read-only transaction + 100 s statement timeout | ✅ | |
| Safety gate (read-only check) | ✅ | |
| Schema check (unknown table or column) | ✅ | |
| Repair of SQL the parser cannot read | ➕ | Python asks the model to fix it. Drupal sends it to the DB, gets an error, then repairs. The user sees the same text. |
| `failure_category` for ungrounded SQL | ⚠️ | Drupal `TOOL_PIPELINE_ERROR`, Python `HALLUCINATION`. Stored in metadata, debug only. |
| `parse_strategy` after a repair | ⚠️ | Drupal keeps the first value. Python sets `"repair"`. |
| Saved `llm_model` | ⚠️ | Drupal saves the model that answered. Python saves the configured name ("sonnet"). |
| Client leaves mid-stream | ⚠️ | Python finishes and saves. Drupal may stop and not save. |
| Session lock key | ⚠️ | Drupal: session id. Python: user + session. Both wait 30 s. |

### 3.5 Results, 200 rows and the CSV download

| Feature | Status | Note |
|---|---|---|
| Send 200 rows to the table, `truncated`, `row_count` = full count | ✅ | |
| `download {chat_id, turn}` only when truncated | ✅ | |
| Full CSV route `/chats/{id}/turns/{n}/csv` | ✅ | Re-runs the saved SQL with no limit and re-checks it. Same 404 / 422 / 500 messages. |
| CSV file name, UTF-8 BOM, label headings, Excel formula guard | ✅ | small edges: Python leaves `nan`/`inf` unprefixed and writes intervals and arrays in Python format |
| **CSV "Colour" column when the answer has no colour column** | ❌ | Drupal `CsvController.php:185-234` (`2cbdd7255`). Python has none. |
| Row values in the JSON | ⚠️ | **Drupal sends the DB text** (`"12.50"`, `"2026-10-01 12:00:00+05:30"`). **Python converts them** (`12.5`, `"2026-10-01T12:00:00+05:30"`). This changes the table cells and the chart labels. See `pipeline/evaluator.py:197-204`. |
| `result.types`, `result.duration_ms` | ❌ | Drupal adds them. Python has none, so the React debug pane shows blanks for "Column types" and "Query time". |
| Server-side totals or statistics over the rows | ✅ | Neither side has them. Totals are grid grouping only. |

### 3.6 Presentation data

| Feature | Status | Note |
|---|---|---|
| Column labels (phrases, words, units) | ✅ | |
| Column order, hidden columns (incl. `assigned_role`) | ✅ | |
| Grouping and aggregation hints | ✅ | |
| Row colour `{at, colours}` from product.yaml | ✅ | small edge in how the id list is cleaned |
| Links as data (url / download / popup) | ✅ | |
| Redactor: public fields allow-list, safe error text | ✅ | |
| "Show the real error when it names no table or column" (`5972714e5`) | ✅ | |
| Welcome text + three starter questions | ✅ | read from the same product.yaml |
| Freshness ("not live") note | ⚠️ | Same tables and same message. Drupal matches any identifier with the table name. Python matches real tables only, and says "no" when the SQL does not parse. |

### 3.7 Charts

| Feature | Status | Note |
|---|---|---|
| Model asks for a chart, chart spec parse and error codes | ✅ | |
| Chart query: gates, 20 s, 100 rows | ✅ | |
| ChartCheck: types, limits, pie to column or line, pivot, palette, notes | ✅ | |
| Chart debug `chart_query.types` | ⚠️ | always `[]` in Python |

### 3.8 Statistics per turn

| Feature | Status | Note |
|---|---|---|
| Tokens (prompt, cache read/write, completion), latency, context size | ✅ | |
| Repair tokens added to the turn | ✅ | |
| `effective_tokens`, monthly sum | ✅ | |
| Monthly token limit (429, `monthly_token_limit`) | ✅ | Python counts only its own chat DB and skips the check when no chat DB is set. |
| `stage_ms` in the response | ❌ | Drupal only |
| Saved `step_timings` | ⚠️ | Drupal: 11 named steps with real start and end. Python: 7 different names, start and end always `null`. |
| `llm_wall_ms`, `repair_ms`, `safety_ms`, `db_ms` | ➕ | Python only |

### 3.9 Chat storage

| Feature | Status | Note |
|---|---|---|
| Tables `sql_chat` / `sql_chat_turn` (Python: `py_` copies in its own chat DB) | ⚠️ | Same columns, keys and cascade, **except `sql_chat.status`, which is missing in Python.** |
| What is saved per turn (question, SQL, status, type, LLM reply, model, tokens, metadata) | ✅ | Rows are never saved, on both sides. |
| Metadata JSON shape and 32 KB trim order | ✅ | `masqueraded` is always false in Python |
| Chat title from the first question | ✅ | |
| Chat list: order, limit, offset, fields, welcome | ✅ | |
| **Chat list: only the last 60 days** | ❌ | `c3232cba8` |
| **Chat list / open / CSV: hide deleted chats (`status = 1`)** | ❌ | `5e318177b` |
| **DELETE `/chats/{id}` (soft delete)** | ❌ | `5e318177b`. **The React page calls it** (`SqlChatbotApi.jsx:76`). |
| Open one chat (GET) | ✅ | same shape |
| Delete a user's chats when the Drupal user is deleted | ❌ | by design (separate DB) |
| Debug endpoint source | ⚠️ | Drupal reads the saved turns. Python keeps the last 50 in memory, so they are lost on restart. |

### 3.10 Endpoints

| Endpoint | Status | Note |
|---|---|---|
| POST ask | ⚠️ | Same body plus a required `user_id` (by design). Python turns **any** `ValueError` into 400 with raw text. Drupal does this only for `InvalidArgumentException`. |
| POST ask/stream (`rows` → `answer` / `error`) | ✅ | Python leaves out `X-Accel-Buffering: no` and `private` |
| `stream_answers` switch | ✅ | |
| GET chats, GET chat | ⚠️ | see 3.9 |
| DELETE chat | ❌ | see 3.9 |
| GET csv | ⚠️ | no Colour column |
| POST debug | ⚠️ | see 3.9 |
| GET health | ⚠️ | Same keys. Python adds `chat_database` and `run_roles` and needs no login. |
| Path prefix | ⚠️ | Drupal `/api/sql-chat/...`, Python bare `/ask` |
| GET /info, static console | ➕ | Python only |

### 3.11 Configuration style

| Feature | Status | Note |
|---|---|---|
| Where settings live | ⚠️ | Drupal: config + admin form + Drupal state for keys. Python: `.env`, restart to apply. By design. |
| Statement timeout 100000, CLI timeout 500, model `sonnet`, effort `medium`, config dir, stream on, monthly limit 0, freshness tables and message | ✅ | same defaults |
| Provider choice | ⚠️ | Drupal: `cli`/`api` + vendor. Python: one flat `LLM_PROVIDER`. |
| Anthropic default model | ⚠️ | Drupal `claude-opus-5`, Python `claude-opus-5-5` |
| One model per vendor | ⚠️ | Drupal keeps one per vendor. Python has one shared `OPENAI_MODEL` with guessed defaults. |
| Model catalog, search box, refresh, key test | ❌ | admin form feature (Python: type the name in `.env`) |
| Freshness table name checks | ⚠️ | Drupal cleans and validates on save. Python only splits. |
| Read-only DB login | ⚠️ | Drupal: `CHATBOT_DB_USER` from `.env`. Python: `DATABASE_READONLY_USER`. |
| Startup self-check | ➕ | Python only |
| Warm CLI pool (4 processes) | ➕ | Python only. **After 90 s it falls back to a fresh call, so the model can be asked twice.** |

### 3.12 LLM providers

| Feature | Status | Note |
|---|---|---|
| Claude CLI flags and env | ✅ | Drupal also sets HOME and USERPROFILE |
| Anthropic API (one call, 1 h cache, 4000 cap, no retry) | ⚠️ | Python uses the SDK with server-side fallback and handles refusal |
| OpenAI-compatible API | ⚠️ | **Python sets no timeout and allows 2 retries (SDK defaults).** Drupal: 500 s, no retry. Python streams; Drupal does not. |
| Effort level, temperature, max tokens | ✅ | |
| API keys | ⚠️ | Drupal: Drupal state. Python: `.env`. |
| Key fallback quirk | ➕ | With `LLM_PROVIDER=openai` and no OpenAI key, Python sends the Groq or Gemini key to api.openai.com |

### 3.13 Identity and access

| Feature | Status | Note |
|---|---|---|
| Who the user is | ⚠️ | Drupal session vs `user_id` in the payload (by design) |
| Name and department lookup, 900 s cache | ✅ | Python cache has no tag clear on user save |
| Who may ask | ⚠️ | Drupal permission vs `CHATBOT_RUN_ROLES` (by design). **Python does not block a blocked user, and gives no special access to uid 1 or admin roles.** |
| Who may read saved chats | ⚠️ | Python needs only a valid user_id, with no role check |
| Who sees debug | ⚠️ | Drupal: any permitted user. Python: localhost only. |
| Admin permission | ❌ | no Python equivalent (whoever edits `.env`) |

### 3.14 Database views

| View | Status | Note |
|---|---|---|
| `tms_attachment_flat`, `tms_task_issue_flat` | ✅ | |
| `tms_task_flat` | ⚠️ | Python migration is stale: it still has `task_elapsed_hours` and lacks the row filter (`display_flag = 1 …`). |
| `tms_initiative_flat`, `tms_role_flat`, `tms_user_flat`, `tms_user_department_flat` | ❌ | No Python SQL file. |
| `tms_issue_flat` | ➕ | Python only, unused |

**These view gaps do not change answers today.** Both sides query the same live database, so the gaps matter only when you rebuild a database from the Python files.

---

## 4. What to do, in order

Items 1–5 and 9–12 are done (see section 0). Items 6–8 and "Can wait" are still open.

### Must have (backend features Drupal has and Python lacks)

1. **Soft delete.** Add `status` to `py_sql_chat`. Add `DELETE /chats/{id}`. Add `status = 1` to list, count, open and CSV.
2. **60-day chat list.** Add `updated_at >= now − 60 days` to list and count.
3. **CSV Colour column.** Port the code from `CsvController.php:185-234`.
4. **Row value format.** Send the DB text the way Drupal does: do not turn Decimal into float, and do not use ISO "T" dates. Or decide that the difference is fine, and write that down.
5. **Working state expiry.** Clear the in-memory state after 1 hour idle.

### Should have (debug and statistics)

6. `stage_ms`, `result.types` and `result.duration_ms` in the response.
7. `step_timings` with Drupal's 11 step names and real start/end.
8. Save the model that answered, not the configured name.

### Should fix (Python-only risks)

9. OpenAI path: set the timeout to 500 s and retries to 0.
10. CLI pool: no second model call after the 90 s cut-off.
11. Block blocked users, and narrow `ValueError → 400`.
12. `promotion/overlay/.env.example` is old. It has no `CHATBOT_RUN_ROLES`, so a build made from it lets nobody ask.

### Can wait

- Model catalog and search (admin UI).
- Add the four missing view SQL files and update `tms_task_flat`.
- Remove `tms_initiative_attributes_flat` from `build_schema_description.py` `TABLES`.

---

## 5. Things found on the Drupal side

These are not Python gaps. They were seen during the check.

- Drupal config keys that no code reads now: `pg_host`, `pg_port`, `pg_database`, `pg_readonly_password` and `debug`. `pg_readonly_user` is read only by update hooks 9010/9012. The other hooks use `.env` `CHATBOT_DB_USER`.
- `ChatResource` `chatId()` does not filter on status. If you ask again in a deleted chat's session, the new turns go into the hidden chat.
- `equalityValue` accepts any value (see 3.3). Python's stricter pattern is better.
- The comment at `ChartCheck.php:17` says "PHP only", but Python now has a port.

---

## 6. Drupal commits and their Python match

| Drupal | Date | What | Python |
|---|---|---|---|
| `c3232cba8` | 29 Oct | Chat list: last 60 days only | ❌ missing |
| `5e318177b` | 26 Oct | Soft-delete a chat | ❌ missing |
| `2cbdd7255` | 26 Oct | CSV Colour column | ❌ missing |
| `212469b91` | 26 Oct | Hide `assigned_role`, new starters | ✅ `2e10213` |
| `d608bdabf` | 22 Oct | Remove entity gazetteer | ✅ `3e6de0f` |
| `40fccd1b5` | 22 Oct | Schema = names, types, descriptions | ✅ `bf7aa11` |
| `5972714e5` | 21 Oct | Show the real error | ✅ `e546b56` |
| `29e76d8cd`, `cbe394096` | 21 Oct | product.yaml, links as data | ✅ `e109f47` |
| `7392434a4` | 16 Oct | 200 rows + full CSV | ✅ `2fb165d` / `c411c9b` |
| `c1fab626d` | 15 Oct | Not-live notice tables | ✅ (no input checks) |
| `3d86016ca`, `6af2d09fb`, `0f422c51c` | 12–13 Oct | Charts | ✅ `0a2e538` |
| `873b8f7e8` | 12 Oct | Weekly report table metadata | ✅ (in the shared YAML) |
| `c2bc1c2bb`, `09837a90a`, `a9079e4e7` | 8–9 Oct | "my issues", file size KB, hide `file_uri` | ✅ (shared YAML + views) |
| `7a641e112`, `c6cbe6afc` | 7–8 Oct | Initiative attributes in site module | ✅ `metadata/site/` |
| `01bd50be0` | 7 Oct | DB login from `.env` | ⚠️ own names |
| `f5e06fabd` | 6 Oct | Time limits, 4000 cap, 1 h cache | ✅ |
| `986223d5c` | 6 Oct | Recent questions + recap from turns | ✅ |
| `7b764ed6e` | 6 Oct | Monthly token cap, dropped filters, days | ✅ |
