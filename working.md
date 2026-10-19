# How the Python chatbot works

This file tells you where each part of the chatbot is. Each item gives the
file and the line. The line numbers are correct on 19 October 2026 (branch
`feat/sync-with-drupal`, commit `e61ec42`). If you change a file, the line
numbers can move. Search for the function name to find the new line.

---

## 1. Files where you change the schema details

The schema details are in YAML files. The chatbot reads only these files. It
does not read the schema from the database.

| File | What it holds |
|---|---|
| [metadata/schema_description.yaml](metadata/schema_description.yaml) | The tables (views), columns, column types, descriptions, primary keys and allowed values. The relationships start at [line 808](metadata/schema_description.yaml#L808). |
| [metadata/business_rules.yaml](metadata/business_rules.yaml) | The business rules and the default filters. |
| [metadata/question_sql_pairs.yaml](metadata/question_sql_pairs.yaml) | Example questions with their correct SQL. |
| [metadata/column_hierarchy.yaml](metadata/column_hierarchy.yaml) | The column order, the hidden columns and the row groups in the result table. |
| [metadata/entity_gazetteer.yaml](metadata/entity_gazetteer.yaml) | The names that the chatbot can find in a question. |
| [metadata/site/](metadata/site/) | The additions for the Arvind site (Initiative attributes). |

The code that reads these files is [pipeline/metadata.py](pipeline/metadata.py):

- `schema()` at [line 51](pipeline/metadata.py#L51).
- `rules()` at [line 62](pipeline/metadata.py#L62).
- `column_hierarchy()` at [line 71](pipeline/metadata.py#L71).
- `pairs()` at [line 80](pipeline/metadata.py#L80).
- `enable_site_metadata()` at [line 33](pipeline/metadata.py#L33). This function adds the `metadata/site/` files.

**Caution:** Keep the five files in `metadata/` the same as the Drupal module
files, byte for byte. Make each change in Drupal first. Then copy the file.

**Caution:** Keep the `metadata/site/` files with CRLF line ends. The Drupal
site module copies have CRLF line ends.

**Note:** The chatbot reads these files one time when it starts. Restart the
server after a change.

---

## 2. Where you set the tables that the chatbot can read for SQL generation

The list of tables starts at
[metadata/schema_description.yaml:8](metadata/schema_description.yaml#L8)
(`tables:`). Each table is one entry below this line. For example,
`tms_task_flat` is at [line 189](metadata/schema_description.yaml#L189).

The chatbot can use a table only if the table is in this list. The code that
makes sure of this:

| File and line | What it does |
|---|---|
| [pipeline/sql_semantics.py:468](pipeline/sql_semantics.py#L468) | `check_against_schema()` finds each table and column in the SQL. It marks the SQL as "not grounded" if a name is not in the list. |
| [pipeline/sql_semantics.py:446](pipeline/sql_semantics.py#L446) | Reads the list from `metadata.schema()`. |
| [pipeline/lean_runner.py:988](pipeline/lean_runner.py#L988) | Stops SQL that is not grounded. This SQL does not go to the database. |

To add a table, add an entry under `tables:`. To remove a table, remove its
entry, and remove each rule, example and hierarchy entry that uses it. For
the full procedure, see [docs/two-databases.md](docs/two-databases.md),
section 1.

---

## 3. Where you give the configuration for the schema (business) database

The business database is database 1. It holds the TMS views.

| File and line | What it holds |
|---|---|
| [.env.example:10-23](.env.example#L10) | `DATABASE_HOST`, `DATABASE_PORT`, `DATABASE_NAME`, `DATABASE_USER`, `DATABASE_PASSWORD`, `DATABASE_READONLY_USER`, `DATABASE_READONLY_PASSWORD`, `DATABASE_STATEMENT_TIMEOUT_MS`. Put the real values in `.env`. |
| [config/settings.py:48-57](config/settings.py#L48) | The settings fields (`pg_host`, `pg_readonly_user` and the other fields). |
| [config/settings.py:242](config/settings.py#L242) | Reads the values from `.env`. |
| [database/connection.py:23](database/connection.py#L23) | `_dsn()` makes the connection details. The SQL from the model always uses the read-only login. |

---

## 4. Where you give the configuration for the database that stores the chats

The chat database is database 2. It holds `py_sql_chat` and
`py_sql_chat_turn`.

| File and line | What it holds |
|---|---|
| [.env.example:44-48](.env.example#L44) | `HISTORY_DATABASE_HOST`, `HISTORY_DATABASE_PORT`, `HISTORY_DATABASE_NAME`, `HISTORY_DATABASE_USER`, `HISTORY_DATABASE_PASSWORD`. |
| [config/settings.py:88-93](config/settings.py#L88) | The settings fields. |
| [config/settings.py:265](config/settings.py#L265) | Reads the values from `.env`. These values do not use the `DATABASE_*` values as a fallback. |
| [config/settings.py:156](config/settings.py#L156) | `problems()` stops the server if the chat database is the business database, or if the two databases use the same login. |
| [pipeline/chat_store.py:142](pipeline/chat_store.py#L142) | `_connect()`. This is the only place that connects to the chat database. |
| [database/migrations/2026-10-19_chat_database.sql](database/migrations/2026-10-19_chat_database.sql) | Makes the chat database, the writer login and the two tables. |

**Note:** `HISTORY_DATABASE_USER` is a database login. It is not the person
who asks the question. That person is the `user_id` in the request. The
`user_id` goes into `py_sql_chat.uid`.

---

## 5. Where the chatbot repairs the SQL

The chatbot repairs SQL one time only. It does this when the database rejects
the SQL, or when the SQL parser cannot read the SQL.

| File and line | What it does |
|---|---|
| [pipeline/lean_runner.py:578](pipeline/lean_runner.py#L578) | `_repair()` sends the question, the SQL and the error to the model again. |
| [pipeline/lean_runner.py:535](pipeline/lean_runner.py#L535) | `_second_attempt()` runs the repair, checks the new SQL with the two gates, and runs it. |
| [pipeline/lean_runner.py:567](pipeline/lean_runner.py#L567) | `_take_repair()` keeps the new SQL and records the old SQL in `repaired_from`. |
| [pipeline/lean_runner.py:967](pipeline/lean_runner.py#L967) | Starts a repair when the parser cannot read the SQL. |
| [pipeline/lean_runner.py:1006](pipeline/lean_runner.py#L1006) | Starts a repair when the database rejects the SQL. |
| [claude/prompts.py:370](claude/prompts.py#L370) | `build_repair_question()` writes the repair question for the model. |

There is also a repair for the question itself. It corrects spelling
mistakes in schema words before the model sees the question:

- `normalize()` at [pipeline/normalize.py:270](pipeline/normalize.py#L270).
- The call is at [pipeline/lean_runner.py:673](pipeline/lean_runner.py#L673).

---

## 6. Where the chatbot decides to use the CLI or an LLM API

| File and line | What it does |
|---|---|
| [.env.example:63](.env.example#L63) | `LLM_PROVIDER`. Use `cli`, `anthropic`, `openai`, `groq` or `gemini`. |
| [config/settings.py:128](config/settings.py#L128) | The setting. The default is `cli`. |
| [llm_api/factory.py:4](llm_api/factory.py#L4) | `get_provider()` gives the CLI provider or an API provider, from `LLM_PROVIDER`. |
| [llm_api/factory.py:19](llm_api/factory.py#L19) | `llm_identity()` gives the mode, the vendor and the model name for each answer. |

---

## 7. Where the chatbot uses the CLI

| File and line | What it does |
|---|---|
| [llm_api/cli_provider.py:299](llm_api/cli_provider.py#L299) | `CLILocalProvider.ask()`. The start for all CLI questions. |
| [llm_api/cli_provider.py:314](llm_api/cli_provider.py#L314) | Uses the warm pool when one is available. |
| [llm_api/cli_provider.py:351](llm_api/cli_provider.py#L351) | Starts a new `claude` process when no pool is available. |
| [llm_api/cli_pool.py:61](llm_api/cli_pool.py#L61) | `cli_workdir()`. Each `claude` process starts in an empty folder, so no `CLAUDE.md` or git status goes into the question. |
| [llm_api/cli_pool.py:74](llm_api/cli_pool.py#L74) | `cli_environment()`. Sets `CLAUDE_CONFIG_DIR`, the one-hour cache and the output limit. |
| [llm_api/cli_provider.py:78](llm_api/cli_provider.py#L78) | `build_command()` makes the `claude` command line. |
| [llm_api/cli_pool.py:180](llm_api/cli_pool.py#L180) | `ClaudePool` keeps CLI processes ready (`CLI_POOL_SIZE`, default 4). |
| [llm_api/cli_pool.py:255](llm_api/cli_pool.py#L255) | Starts one warm process. |
| [llm_api/cli_pool.py:303](llm_api/cli_pool.py#L303) | `ClaudePool.ask()` sends the question to a warm process. |

**Note:** The warm pool is the main reason why Python is faster than Drupal.
A new CLI process needs approximately 3 to 4 seconds to start. Drupal starts
a new process for each question.

---

## 8. Where the chatbot uses an LLM API

| File and line | What it does |
|---|---|
| [llm_api/anthropic_provider.py:42](llm_api/anthropic_provider.py#L42) | `AnthropicProvider`, for `LLM_PROVIDER=anthropic`. |
| [llm_api/anthropic_provider.py:60](llm_api/anthropic_provider.py#L60) | The call to the Anthropic Messages API. The system prompt is cached for one hour ([line 66](llm_api/anthropic_provider.py#L66)). |
| [llm_api/openai_provider.py:52](llm_api/openai_provider.py#L52) | `OpenAIProvider`, for `openai`, `groq` and `gemini`. |
| [llm_api/openai_provider.py:107](llm_api/openai_provider.py#L107) | The call to the chat completions API. |
| [llm_api/openai_provider.py:153](llm_api/openai_provider.py#L153) | The same call with streaming. |

**Caution:** An API call costs money for each question.

---

## 9. How you start the project

The script is [scripts/serve_api.py](scripts/serve_api.py). It is a FastAPI
server.

| File and line | What it does |
|---|---|
| [scripts/serve_api.py:1104](scripts/serve_api.py#L1104) | `main()`. Reads the command options. |
| [scripts/serve_api.py:1121](scripts/serve_api.py#L1121) | Adds the site metadata. |
| [scripts/serve_api.py:1145](scripts/serve_api.py#L1145) | Starts the server with uvicorn. |
| [scripts/serve_api.py:431](scripts/serve_api.py#L431) | `Runtime`. Loads the settings and starts the warm pool. |

Procedure:

1. Install the packages: `.venv\Scripts\python.exe -m pip install -r requirements.txt`.
2. Start the server: `.venv\Scripts\python.exe scripts\serve_api.py`.
3. Open `http://127.0.0.1:8000/?user_id=<TMS user id>` in a browser.
4. To change the port, add `--port 8011`.

The server shows the two databases, the logins and the run roles when it
starts. It does not show the passwords.

---

## 10. Where the chatbot runs the SQL and gets information

| File and line | What it does |
|---|---|
| [database/connection.py:103](database/connection.py#L103) | `run_readonly()`. Runs one statement in a READ ONLY transaction, with a time limit, as the read-only login. |
| [pipeline/lean_runner.py:389](pipeline/lean_runner.py#L389) | `_execute()`. The pipeline calls `run_readonly()` through this function. |
| [pipeline/lean_runner.py:909](pipeline/lean_runner.py#L909) | Runs the main SQL of the answer. |
| [pipeline/lean_runner.py:403](pipeline/lean_runner.py#L403) | `_run_chart_query()`. Runs the chart SQL, if the model gives one. |
| [pipeline/identity_provider.py:26](pipeline/identity_provider.py#L26) | `resolve_identity()`. Gets the name and the departments of the user. |
| [pipeline/run_access.py:59](pipeline/run_access.py#L59) | `user_roles()`. Gets the Drupal roles of the user from `vf_user__roles`. |

---

## 11. Where the chatbot writes the schema context (the system prompt)

| File and line | What it does |
|---|---|
| [claude/prompts.py:343](claude/prompts.py#L343) | `build_lean_system_prompt()`. Puts the system prompt together. |
| [claude/prompts.py:119](claude/prompts.py#L119) | `LEAN_SYSTEM_PROMPT`. The fixed instructions. |
| [claude/prompts.py:274](claude/prompts.py#L274) | `_render_schema()`. Writes the tables and columns. |
| [claude/prompts.py:321](claude/prompts.py#L321) | `_render_rules()`. Writes the business rules. |
| [claude/prompts.py:333](claude/prompts.py#L333) | `_render_examples()`. Writes the example questions and SQL. |
| [pipeline/context.py:715](pipeline/context.py#L715) | `CONTEXT_GUIDANCE`. Tells the model how to read the conversation context. |

**Note:** The system prompt is the same for each question. The chatbot builds
it one time and keeps it (`lru_cache`). It must be the same as the Drupal
system prompt, byte for byte.

---

## 12. Where the chatbot writes the conversation context

| File and line | What it does |
|---|---|
| [pipeline/context.py:644](pipeline/context.py#L644) | `render_context()`. Writes the context block: the open question, a removed filter, the recap and the recent questions. |
| [pipeline/context.py:634](pipeline/context.py#L634) | `remember_question()`. Adds the question to the recent questions (10 maximum, 160 characters each). |
| [pipeline/context.py:351](pipeline/context.py#L351) | `accept_recap()`. Keeps the summary from the model (320 characters maximum). |
| [pipeline/context.py:487](pipeline/context.py#L487) | `classify_turn()`. Decides if the question is new, a follow-up, a switch or a rebase. |
| [pipeline/context.py:553](pipeline/context.py#L553) | `update_state()`. Updates the state from the SQL that ran. |
| [pipeline/identity.py:42](pipeline/identity.py#L42) | `render_identity()`. Writes the block for the user who asks. |
| [pipeline/chat_store.py:164](pipeline/chat_store.py#L164) | `load()`. Gets the recent questions and the recap from the saved chat. |

---

## 13. Where the chatbot puts the prompt together

| File and line | What it does |
|---|---|
| [pipeline/lean_runner.py:626](pipeline/lean_runner.py#L626) | `run_turn()`. Controls one question from start to end. |
| [pipeline/lean_runner.py:759](pipeline/lean_runner.py#L759) | Writes the context block. |
| [pipeline/lean_runner.py:766](pipeline/lean_runner.py#L766) | Puts the identity block on top of the context block. |
| [pipeline/lean_runner.py:774](pipeline/lean_runner.py#L774) | Gives the context block to the session. |
| [pipeline/lean_runner.py:820](pipeline/lean_runner.py#L820) | Sends the question to the provider. |
| [claude/prompts.py:71](claude/prompts.py#L71) | `build_user_prompt()`. Makes the user prompt: context block, then `Question: ...`, then the closing instruction. |
| [scripts/serve_api.py:593](scripts/serve_api.py#L593) | The server calls `run_turn()`. |

The model gets two parts:

1. The system prompt (item 11). It is the same for each question.
2. The user prompt (this item). It changes for each question.

---

## 14. Where the chatbot checks for ambiguity

The chatbot checks for ambiguity at three points.

| File and line | What it does |
|---|---|
| [pipeline/followup.py:171](pipeline/followup.py#L171) | `clarify_entity()`. Before the model, finds a name that matches two or more values (for example "AR_YD"). Then it asks the user to select one. |
| [pipeline/lean_runner.py:786](pipeline/lean_runner.py#L786) | Calls `clarify_entity()`. If it finds an ambiguity, the model is not asked. |
| [claude/parser.py:156](claude/parser.py#L156) | `parse_clarification()`. Reads a clarifying question from the reply of the model. |
| [claude/parser.py:313](claude/parser.py#L313) | `parse_options()`. Reads the choices that the model gives. |
| [pipeline/lean_runner.py:853](pipeline/lean_runner.py#L853) | If the model asks a question, the chatbot does not use SQL for this turn. |
| [pipeline/followup.py:550](pipeline/followup.py#L550) | `clarification_followup()`. Makes the choice buttons for the user. |
| [pipeline/followup.py:703](pipeline/followup.py#L703) | `resolve_clarification()`. Reads the answer of the user to the clarifying question. |
| [pipeline/lean_runner.py:691](pipeline/lean_runner.py#L691) | Calls `resolve_clarification()` on the next turn. |
| [pipeline/context.py:450](pipeline/context.py#L450) | `detect_entity()`. Finds a known name in the question. |

---

## More information

### The path of one question

1. The browser sends `POST /ask` or `POST /ask/stream`
   ([scripts/serve_api.py:950](scripts/serve_api.py#L950),
   [line 997](scripts/serve_api.py#L997)).
2. The server checks the `user_id` and the run role
   ([scripts/serve_api.py:490](scripts/serve_api.py#L490)).
3. The pipeline repairs the spelling of the question (item 5).
4. The pipeline decides how the question relates to the conversation (item 12).
5. The pipeline checks for ambiguity (item 14).
6. The pipeline puts the prompt together and asks the model (item 13).
7. The pipeline reads the SQL, checks it with the two gates, and runs it (items 2 and 10).
8. If the database rejects the SQL, the pipeline repairs it one time (item 5).
9. The pipeline updates the state, makes the follow-up buttons and saves the chat (item 4).

### Who can ask a question

| File and line | What it does |
|---|---|
| [.env.example:31](.env.example#L31) | `CHATBOT_RUN_ROLES`. The Drupal roles that can ask questions. |
| [pipeline/run_access.py:46](pipeline/run_access.py#L46) | `user_id_from()`. Refuses a missing or incorrect `user_id` (HTTP 400). |
| [pipeline/run_access.py:80](pipeline/run_access.py#L80) | `check_run()`. Refuses a user without a listed role (HTTP 403). |

### The two safety gates

| File and line | Gate |
|---|---|
| [pipeline/safety.py:77](pipeline/safety.py#L77) | `assert_read_only()`. Lets only one SELECT statement through. |
| [pipeline/sql_semantics.py:468](pipeline/sql_semantics.py#L468) | `check_against_schema()`. Lets only the listed tables and columns through. |

The chatbot runs the SQL only if the SQL passes the two gates. The read-only
login and the READ ONLY transaction give a third barrier.

### Charts

- The system prompt tells the model how to give a chart
  ([claude/prompts.py:177](claude/prompts.py#L177)).
- [pipeline/chart_check.py](pipeline/chart_check.py) checks the chart.
- The answer gives the chart in `result.chart`.
- The Python console does not draw charts. The React frontend draws charts.

### Speed settings

| Setting | Effect |
|---|---|
| `CLI_POOL_SIZE` | The number of warm CLI processes. Use 0 to stop the pool. |
| `STREAM_ANSWERS` | `true` sends the table before the answer text. |
| `CLAUDE_EFFORT_LEVEL` | `low` is faster than `medium`. |
| `CLAUDE_CONFIG_DIR` | Use a folder with only the Claude login (for example `.claude-wren`). If it is empty, your own plugins, hooks and `CLAUDE.md` go into each question. This adds approximately 4,700 tokens at full price. |

### How to test

1. Run the unit tests (no database, no model):
   `.venv\Scripts\python.exe -m pytest -q -m "not integration"`
2. Start the server and open `http://127.0.0.1:8000/health`. Make sure that
   `ok` is `true`.
3. Send `POST /ask` without `user_id`. Make sure that the result is HTTP 400.
4. Run the parity check against Drupal. See [docs/gotchas.md](docs/gotchas.md),
   section 2.

### Other documents

- [docs/two-databases.md](docs/two-databases.md): the two databases, the run
  roles and the chat login.
- [docs/gotchas.md](docs/gotchas.md): known problems and their solutions.
