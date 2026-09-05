# Wren + Claude Code Text-to-SQL Evaluation POC — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a runnable benchmark that measures how reliably Claude Code CLI + Wren AI generate correct PostgreSQL for a semantically-rich 3-table schema, while keeping database rows out of the LLM interaction.

**Architecture:** Python orchestrates only. It shells out to `claude -p` with a `--strict-mcp-config` pointing at a local `wren serve mcp` process; Wren supplies schema, business rules and NL→SQL exemplars and produces SQL; Python parses that SQL, safety-gates it, executes it against a read-only PostgreSQL role, and compares results to hand-written ground truth. Python contains no SQL planner, query builder or SQL reasoning of any kind.

**Tech Stack:** Python 3.12, `wrenai[postgres,mcp,memory]` 0.13.4, Claude Code CLI 2.1.234, PostgreSQL 16.12, `psycopg[binary]` 3, `sqlglot`, `pyyaml`, `python-dotenv`, `pytest`.

**Reference spec:** `docs/superpowers/specs/2026-09-04-wren-claude-poc-design.md`

## Global Constraints

- **No Docker.** No `docker-compose.yml`, no Dockerfile, no container commands anywhere.
- **No Anthropic API.** No `anthropic` SDK, no `ANTHROPIC_API_KEY`, no HTTP to Anthropic. Claude is reached only via `subprocess` on the local `claude` binary; authentication stays inside the local Claude Code install.
- **No custom planner (§25).** Python must never decide how SQL should be constructed. Hand-written ground-truth SQL is fixture data, not a planner.
- **Row data must never reach Claude.** `mcp__wren__run_sql` and `mcp__wren__query_cube` are always in `--disallowedTools`; the `strict` config additionally runs `wren serve mcp --no-connect` so they are never registered.
- **Read-only benchmark.** Generated SQL passes a `sqlglot` safety gate and executes as a read-only PG role inside a `READ ONLY` transaction with a statement timeout.
- **Never log credentials.** No password, token or full environment dump in any log, report or error message.
- **Package named `wren_setup/`, not `wren/`** — a top-level `wren/` shadows the installed `wren` module from `wrenai`.
- **Determinism:** seed data uses fixed IDs and literal inserts; dates are relative to `CURRENT_DATE`; "top N" questions are seeded tie-free.
- **Exemplars ⟂ benchmark questions:** no `question_sql_pairs.yaml` entry may equal a `benchmark/questions.yaml` entry. Enforced by a test.
- This is not a git repository. Commit steps are omitted; run `git init` first if commits are wanted.

---

## File Structure

| Path | Responsibility |
|---|---|
| `config/settings.py` | Load `.env` into a frozen `Settings` dataclass. Single source of config. |
| `config/logging.py` | `get_logger(name)`; redacting formatter that never emits secrets. |
| `database/schema.sql` | 3 tables, FKs, indexes, read-only role grants. |
| `database/seed.sql` | Deterministic 15/8/50 rows, dates relative to `CURRENT_DATE`. |
| `database/connection.py` | `connect()`, `run_readonly(sql, timeout)` → `QueryResult`. |
| `database/setup.py` | Apply schema + seed; create `wren_ro` role. |
| `metadata/schema_description.yaml` | Business meaning of every table/column + enum semantics. |
| `metadata/business_rules.yaml` | Named business rules → `instructions.md`. |
| `metadata/question_sql_pairs.yaml` | Wren-native `pairs:` NL→SQL exemplars. |
| `wren_setup/build.py` | Introspect via `wren context init`; emit 4 project configs A–D. |
| `wren_setup/mcp_config.py` | Generate the `--mcp-config` JSON per config. |
| `wren_setup/helpers.py` | Thin `wren` CLI subprocess wrapper. |
| `claude/prompts.py` | System prompt + per-question user prompt. |
| `claude/cli.py` | Invoke `claude -p`, parse `stream-json`, return `ClaudeRun`. |
| `claude/parser.py` | 5-strategy SQL extraction → `ParsedSQL`. |
| `benchmark/models.py` | Dataclasses: `Question`, `QuestionResult`, `ClaudeRun`, `ParsedSQL`, `QueryResult`. |
| `benchmark/safety.py` | `assert_read_only(sql)` — sqlglot gate. |
| `benchmark/evaluator.py` | Normalisation + permutation-aware result comparison. |
| `benchmark/classify.py` | Failure classification (deterministic → heuristic). |
| `benchmark/runner.py` | Per-question and full-run orchestration. |
| `benchmark/report.py` | `results/latest.{json,csv,md}`. |
| `benchmark/questions.yaml` | ~80 questions, categories A–S, with `expected_sql`. |
| `scripts/*.py` | `check_environment`, `setup_demo`, `verify_ground_truth`, `run_single`, `run_benchmark`. |
| `tests/*.py` | Unit tests; live ones marked `@pytest.mark.integration`. |
| `docs/*.md` | architecture, data-flow, privacy, v2-chat-context. |

---

## Task 1: Config, logging, project skeleton

**Files:**
- Create: `config/settings.py`, `config/logging.py`, `.env.example`, `.gitignore`, `requirements.txt`
- Test: `tests/test_settings.py`

**Interfaces:**
- Produces: `Settings` frozen dataclass with `pg_host, pg_port, pg_database, pg_user, pg_password, pg_readonly_user, pg_readonly_password, wren_home, wren_project_root, wren_memory_backend, claude_command, claude_model, claude_timeout_seconds, benchmark_config, debug`; `load_settings(env_file=None) -> Settings`; `get_logger(name) -> Logger`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_settings.py
from config.settings import load_settings

def test_load_settings_reads_env_file(tmp_path):
    env = tmp_path / ".env"
    env.write_text(
        "DATABASE_HOST=db.local\nDATABASE_PORT=5433\nDATABASE_NAME=wren_demo\n"
        "DATABASE_USER=postgres\nDATABASE_PASSWORD=secret\n"
    )
    s = load_settings(env)
    assert s.pg_host == "db.local"
    assert s.pg_port == 5433
    assert s.pg_database == "wren_demo"

def test_password_never_appears_in_repr(tmp_path):
    env = tmp_path / ".env"
    env.write_text("DATABASE_PASSWORD=sup3rsecret\n")
    s = load_settings(env)
    assert "sup3rsecret" not in repr(s)
    assert "sup3rsecret" not in str(s)
```

- [ ] **Step 2: Run it — expect ModuleNotFoundError**

Run: `.venv/Scripts/python.exe -m pytest tests/test_settings.py -v`

- [ ] **Step 3: Implement `config/settings.py`**

Frozen dataclass; `pg_password` and `pg_readonly_password` stored in `field(repr=False)` so `repr()` cannot leak them. Defaults match `.env.example`. `load_settings` uses `python-dotenv`'s `dotenv_values` (never mutates `os.environ` globally).

- [ ] **Step 4: Implement `config/logging.py`**

`get_logger(name)` returns a stdlib logger with a `RedactingFormatter` that replaces any substring equal to a known secret with `***`. Level from `DEBUG` env.

- [ ] **Step 5: Write `.env.example`, `.gitignore`, `requirements.txt`**

`.env.example` carries every key with safe placeholder values and **no** `ANTHROPIC_API_KEY`. `.gitignore` covers `.venv/`, `.env`, `__pycache__/`, `results/*.json`, `wren_projects/`. `requirements.txt` pins the stack listed above.

- [ ] **Step 6: Run tests — expect PASS**

---

## Task 2: Database schema, seed and read-only access

**Files:**
- Create: `database/schema.sql`, `database/seed.sql`, `database/connection.py`, `database/setup.py`
- Test: `tests/test_database.py`

**Interfaces:**
- Consumes: `Settings` from Task 1.
- Produces: `connect(settings, readonly=False) -> psycopg.Connection`; `run_readonly(settings, sql, timeout_ms) -> QueryResult`; `QueryResult(columns: list[str], rows: list[tuple], duration_ms: float, error: str | None, sqlstate: str | None)`.

- [ ] **Step 1: Write `database/schema.sql`**

`users(id, full_name, email, department, role, status)`, `workflows(id, name, description, category, status, owner_user_id, created_at, updated_at)`, `tasks(id, workflow_id, name, description, status, priority, assigned_user_id, due_date, completed_at, created_at)`. FKs exactly as §8. Drops are `DROP TABLE IF EXISTS ... CASCADE` in dependency order so re-running is idempotent.

- [ ] **Step 2: Write `database/seed.sql`**

Literal inserts with explicit ids: 15 users, 8 workflows, 50 tasks. Dates relative to `CURRENT_DATE`. Must satisfy every coverage bullet in §9, and must be tie-free at every "top N" boundary used by `questions.yaml`.

- [ ] **Step 3: Write the failing tests**

```python
# tests/test_database.py
import pytest
from database.connection import run_readonly

pytestmark = pytest.mark.integration

def test_row_counts(settings):
    for table, expected in [("users", 15), ("workflows", 8), ("tasks", 50)]:
        r = run_readonly(settings, f"SELECT count(*) FROM {table}", 5000)
        assert r.rows[0][0] == expected

def test_foreign_keys_present(settings):
    r = run_readonly(settings, """
        SELECT count(*) FROM information_schema.table_constraints
        WHERE constraint_type='FOREIGN KEY' AND table_schema='public'
    """, 5000)
    assert r.rows[0][0] == 3

def test_coverage_invariants(settings):
    checks = {
        "workflow with zero tasks":
            "SELECT count(*) FROM workflows w WHERE NOT EXISTS "
            "(SELECT 1 FROM tasks t WHERE t.workflow_id=w.id)",
        "user with zero assigned tasks":
            "SELECT count(*) FROM users u WHERE NOT EXISTS "
            "(SELECT 1 FROM tasks t WHERE t.assigned_user_id=u.id)",
        "overdue task":
            "SELECT count(*) FROM tasks WHERE due_date < CURRENT_DATE "
            "AND status <> 'COMPLETED'",
        "null completed_at":
            "SELECT count(*) FROM tasks WHERE completed_at IS NULL",
        "inactive user":
            "SELECT count(*) FROM users WHERE status='INACTIVE'",
        "blocked task":
            "SELECT count(*) FROM tasks WHERE status='BLOCKED'",
    }
    for label, sql in checks.items():
        assert run_readonly(settings, sql, 5000).rows[0][0] > 0, label

def test_seed_is_deterministic(settings):
    a = run_readonly(settings, "SELECT id, full_name, email FROM users ORDER BY id", 5000)
    b = run_readonly(settings, "SELECT id, full_name, email FROM users ORDER BY id", 5000)
    assert a.rows == b.rows

def test_readonly_role_cannot_write(settings):
    r = run_readonly(settings, "INSERT INTO users(id, full_name) VALUES (999,'x')", 5000)
    assert r.error is not None
```

- [ ] **Step 4: Run — expect failure (no module / no tables)**

- [ ] **Step 5: Implement `database/connection.py`**

`run_readonly` opens a connection as the read-only role, issues `SET TRANSACTION READ ONLY` and `SET LOCAL statement_timeout`, executes, and returns `QueryResult`. All `psycopg.Error`s are caught and returned in `error`/`sqlstate` rather than raised, because the benchmark must record failures, not crash on them.

- [ ] **Step 6: Implement `database/setup.py`**

Applies `schema.sql` then `seed.sql` as the owner; creates role `wren_ro` with `LOGIN`, `GRANT CONNECT`/`USAGE`/`SELECT` only, and `ALTER DEFAULT PRIVILEGES`. Idempotent.

- [ ] **Step 7: Run `python scripts/setup_demo.py` then the tests — expect PASS**

---

## Task 3: Semantic metadata

**Files:**
- Create: `metadata/schema_description.yaml`, `metadata/business_rules.yaml`, `metadata/question_sql_pairs.yaml`
- Test: `tests/test_metadata.py`

**Interfaces:**
- Produces: `load_metadata()` helpers in `wren_setup/build.py` consume these three files.

- [ ] **Step 1: Write `metadata/schema_description.yaml`**

Every table and every column documented with business meaning, not restated names. Enum values carry their operational consequence (`ACTIVE: user is available and may receive new task assignments`). Includes top-level `terminology`, `relationships` and `ambiguities` sections; the owner-vs-assignee distinction is stated explicitly under `ambiguities`.

- [ ] **Step 2: Write `metadata/business_rules.yaml`**

Each rule: `name`, `definition` (prose), `sql_fragment`. Covers active user, completed/open/overdue task, owner join, assignee join, `COUNT(tasks.id)` vs `COUNT(DISTINCT workflows.id)`, and the explicit warning never to confuse owner with assignee.

- [ ] **Step 3: Write `metadata/question_sql_pairs.yaml`**

Wren-native shape: top-level `pairs:` list of `{nl_query, sql}`. Starts from the nine confirmed §12 examples.

- [ ] **Step 4: Write the failing tests**

```python
# tests/test_metadata.py
import yaml, pathlib, pytest
from database.connection import run_readonly

ROOT = pathlib.Path(__file__).resolve().parents[1]

def _load(name):
    return yaml.safe_load((ROOT / "metadata" / name).read_text(encoding="utf-8"))

def test_every_column_is_described():
    desc = _load("schema_description.yaml")
    expected = {
        "users": {"id","full_name","email","department","role","status"},
        "workflows": {"id","name","description","category","status",
                      "owner_user_id","created_at","updated_at"},
        "tasks": {"id","workflow_id","name","description","status","priority",
                  "assigned_user_id","due_date","completed_at","created_at"},
    }
    for table, cols in expected.items():
        documented = set(desc["tables"][table]["columns"])
        assert documented == cols, f"{table}: {cols ^ documented}"

def test_descriptions_are_not_trivial_restatements():
    desc = _load("schema_description.yaml")
    for table, tdef in desc["tables"].items():
        for col, cdef in tdef["columns"].items():
            text = cdef["description"].strip().lower()
            assert len(text) > 40, f"{table}.{col} description too thin"
            assert text != f"{col.replace('_',' ')} of the {table[:-1]}"

def test_pairs_disjoint_from_benchmark():
    pairs = {p["nl_query"].strip().lower()
             for p in _load("question_sql_pairs.yaml")["pairs"]}
    qs = yaml.safe_load((ROOT / "benchmark" / "questions.yaml").read_text(encoding="utf-8"))
    bench = {q["question"].strip().lower() for q in qs["questions"]}
    assert not (pairs & bench), f"exemplar leak: {pairs & bench}"

@pytest.mark.integration
def test_every_pair_sql_executes(settings):
    for p in _load("question_sql_pairs.yaml")["pairs"]:
        r = run_readonly(settings, p["sql"], 10000)
        assert r.error is None, f"{p['nl_query']}: {r.error}"
```

- [ ] **Step 5: Run — expect PASS once all three files are complete**

---

## Task 4: Wren project build (configs A–D)

**Files:**
- Create: `wren_setup/__init__.py`, `wren_setup/helpers.py`, `wren_setup/build.py`, `wren_setup/mcp_config.py`
- Test: `tests/test_wren_setup.py`

**Interfaces:**
- Consumes: `Settings`; the three `metadata/` files.
- Produces: `run_wren(args: list[str], env: dict, timeout: int) -> CompletedProcess`; `build_config(name: Literal["A","B","C","D"], settings) -> Path`; `write_mcp_config(config_name, privacy_mode, settings) -> Path`; `allowed_tools(privacy_mode) -> list[str]`; `DISALLOWED_TOOLS = ["mcp__wren__run_sql", "mcp__wren__query_cube"]`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_wren_setup.py
import json
from wren_setup.mcp_config import write_mcp_config, allowed_tools, DISALLOWED_TOOLS

def test_strict_mode_passes_no_connect(tmp_settings):
    path = write_mcp_config("D", "strict", tmp_settings)
    cfg = json.loads(path.read_text())
    args = cfg["mcpServers"]["wren"]["args"]
    assert "serve" in args and "mcp" in args and "--no-connect" in args

def test_validated_mode_omits_no_connect(tmp_settings):
    cfg = json.loads(write_mcp_config("D", "validated", tmp_settings).read_text())
    assert "--no-connect" not in cfg["mcpServers"]["wren"]["args"]

def test_row_returning_tools_always_disallowed():
    assert DISALLOWED_TOOLS == ["mcp__wren__run_sql", "mcp__wren__query_cube"]
    for mode in ("strict", "validated"):
        assert not set(allowed_tools(mode)) & set(DISALLOWED_TOOLS)

def test_dry_run_only_offered_when_connected():
    assert "mcp__wren__dry_run" not in allowed_tools("strict")
    assert "mcp__wren__dry_run" in allowed_tools("validated")

def test_config_env_isolates_project_and_memory(tmp_settings):
    a = json.loads(write_mcp_config("A", "strict", tmp_settings).read_text())
    d = json.loads(write_mcp_config("D", "strict", tmp_settings).read_text())
    ea, ed = a["mcpServers"]["wren"]["env"], d["mcpServers"]["wren"]["env"]
    assert ea["WREN_PROJECT_HOME"] != ed["WREN_PROJECT_HOME"]
    assert ea["WREN_MEMORY_DIR"] != ed["WREN_MEMORY_DIR"]
```

- [ ] **Step 2: Run — expect ModuleNotFoundError**

- [ ] **Step 3: Implement `wren_setup/helpers.py`**

`run_wren` invokes the venv's `wren` executable with an explicit `env`, capturing stdout/stderr and raising a `WrenError` carrying stderr on non-zero exit.

- [ ] **Step 4: Implement `wren_setup/mcp_config.py`**

Emits `{"mcpServers": {"wren": {"command": <wren path>, "args": [...], "env": {...}}}}`. `args` is `["serve","mcp","--transport","stdio"]` plus `--no-connect` in strict mode. `env` sets `WREN_PROJECT_HOME`, `WREN_MEMORY_DIR`, `WREN_MEMORY_BACKEND`. `allowed_tools` returns the read-only context/knowledge/`dry_plan` tool list, adding `dry_run` only for `validated`.

- [ ] **Step 5: Implement `wren_setup/build.py`**

For config A: `wren context init` introspecting PostgreSQL (setup-time metadata read only), then `wren context validate`. For B/C/D: copy A's MDL and merge `description` fields from `schema_description.yaml`. For C/D: render `business_rules.yaml` into `instructions.md`. For D: `wren memory load metadata/question_sql_pairs.yaml --overwrite` with `WREN_MEMORY_BACKEND=lancedb`, then `wren memory status` to confirm the backend actually resolved to lancedb rather than silently downgrading to grep.

- [ ] **Step 6: Run the build, then `wren context validate` on all four — expect clean**

- [ ] **Step 7: Run tests — expect PASS**

---

## Task 5: SQL parser and safety gate

**Files:**
- Create: `claude/__init__.py`, `claude/parser.py`, `benchmark/safety.py`, `benchmark/models.py`
- Test: `tests/test_parser.py`, `tests/test_safety.py`

**Interfaces:**
- Produces: `parse_sql(text) -> ParsedSQL`; `ParsedSQL(sql: str | None, strategy: str, raw: str)`; `assert_read_only(sql) -> None` raising `UnsafeSQLError`.

- [ ] **Step 1: Write the failing parser tests**

```python
# tests/test_parser.py
from claude.parser import parse_sql

def test_strategy_json_object():
    p = parse_sql('{"sql": "SELECT 1"}')
    assert p.sql == "SELECT 1" and p.strategy == "json"

def test_strategy_sql_fence():
    p = parse_sql("Here you go:\n```sql\nSELECT * FROM users\n```\nHope that helps.")
    assert p.sql == "SELECT * FROM users" and p.strategy == "sql_fence"

def test_strategy_generic_fence():
    p = parse_sql("```\nSELECT 1\n```")
    assert p.sql == "SELECT 1" and p.strategy == "generic_fence"

def test_strategy_embedded_json():
    p = parse_sql('Result below.\n{"sql": "SELECT 2"}\nDone.')
    assert p.sql == "SELECT 2" and p.strategy == "embedded_json"

def test_strategy_bare_statement():
    p = parse_sql("SELECT id FROM tasks WHERE status = 'TODO'")
    assert p.sql.startswith("SELECT id") and p.strategy == "bare"

def test_prefers_last_sql_fence_over_earlier_draft():
    p = parse_sql("```sql\nSELECT 1\n```\nActually:\n```sql\nSELECT 2\n```")
    assert p.sql == "SELECT 2"

def test_cte_is_recognised_as_bare_statement():
    p = parse_sql("WITH c AS (SELECT 1 AS n) SELECT n FROM c")
    assert p.sql.startswith("WITH c AS") and p.strategy == "bare"

def test_returns_none_when_no_sql():
    p = parse_sql("I could not answer that.")
    assert p.sql is None and p.strategy == "none"

def test_strips_trailing_semicolon_and_commentary():
    p = parse_sql("```sql\n-- find users\nSELECT 1;\n```")
    assert p.sql.endswith("SELECT 1")
```

- [ ] **Step 2: Write the failing safety tests**

```python
# tests/test_safety.py
import pytest
from benchmark.safety import assert_read_only, UnsafeSQLError

@pytest.mark.parametrize("sql", [
    "INSERT INTO users VALUES (1)", "UPDATE users SET status='X'",
    "DELETE FROM users", "DROP TABLE users", "ALTER TABLE users ADD c int",
    "TRUNCATE users", "CREATE TABLE t(x int)", "GRANT ALL ON users TO x",
    "REVOKE ALL ON users FROM x", "SELECT 1; DROP TABLE users",
    "COPY users TO '/tmp/x.csv'", "DO $$ BEGIN END $$",
])
def test_rejects_dangerous_sql(sql):
    with pytest.raises(UnsafeSQLError):
        assert_read_only(sql)

@pytest.mark.parametrize("sql", [
    "SELECT * FROM users",
    "WITH c AS (SELECT 1 AS n) SELECT n FROM c",
    "SELECT u.full_name, count(t.id) FROM users u "
    "LEFT JOIN tasks t ON t.assigned_user_id=u.id GROUP BY u.full_name",
    "SELECT rank() OVER (ORDER BY id) FROM tasks",
])
def test_allows_read_only_sql(sql):
    assert_read_only(sql)
```

- [ ] **Step 3: Run both — expect ModuleNotFoundError**

- [ ] **Step 4: Implement `benchmark/models.py`**

Dataclasses only, no behaviour: `Question`, `ParsedSQL`, `ClaudeRun`, `QueryResult`, `QuestionResult` carrying every field named in §19.

- [ ] **Step 5: Implement `claude/parser.py`**

Five ordered strategies, each a separate small function so each is independently testable. Strips SQL comments and trailing semicolons before returning.

- [ ] **Step 6: Implement `benchmark/safety.py`**

`sqlglot.parse` the text; reject if it yields more than one statement or if any statement is not a `Select`/`With` at the root, or if the AST contains any DDL/DML node. A regex screen for the §17 keyword list backs the AST check up.

- [ ] **Step 7: Run both test files — expect PASS**

---

## Task 6: Claude CLI wrapper and prompts

**Files:**
- Create: `claude/prompts.py`, `claude/cli.py`
- Test: `tests/test_claude_cli.py`

**Interfaces:**
- Consumes: `write_mcp_config`, `allowed_tools`, `DISALLOWED_TOOLS`, `parse_sql`.
- Produces: `ClaudeRun(ok, stdout, stderr, exit_code, timed_out, duration_ms, tools_used: list[str], result_text, cost_usd, session_id, error)`; `detect_claude(cmd) -> str | None`; `ask_claude(question, config_name, privacy_mode, settings) -> ClaudeRun`; `SYSTEM_PROMPT: str`; `build_user_prompt(question) -> str`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_claude_cli.py
import json
from claude.cli import build_command, parse_stream_json
from wren_setup.mcp_config import DISALLOWED_TOOLS

def test_command_is_headless_and_strict(tmp_settings, tmp_path):
    cmd = build_command("Show all users", tmp_path / "mcp.json", "strict", tmp_settings)
    assert "-p" in cmd
    assert "--strict-mcp-config" in cmd
    assert cmd[cmd.index("--output-format") + 1] == "stream-json"
    assert "--verbose" in cmd

def test_command_always_disallows_row_tools(tmp_settings, tmp_path):
    cmd = build_command("q", tmp_path / "mcp.json", "validated", tmp_settings)
    tail = cmd[cmd.index("--disallowedTools") + 1:]
    for tool in DISALLOWED_TOOLS:
        assert tool in tail

def test_command_carries_no_api_key(tmp_settings, tmp_path):
    joined = " ".join(build_command("q", tmp_path / "m.json", "strict", tmp_settings))
    assert "ANTHROPIC" not in joined.upper()

def test_parse_stream_json_collects_tools_and_result():
    stream = "\n".join(json.dumps(e) for e in [
        {"type": "assistant", "message": {"content": [
            {"type": "tool_use", "name": "mcp__wren__get_mdl"},
            {"type": "tool_use", "name": "mcp__wren__recall_queries"}]}},
        {"type": "result", "subtype": "success", "is_error": False,
         "result": "```sql\nSELECT 1\n```", "duration_ms": 4200,
         "total_cost_usd": 0.01, "session_id": "abc"},
    ])
    run = parse_stream_json(stream)
    assert run.tools_used == ["mcp__wren__get_mdl", "mcp__wren__recall_queries"]
    assert "SELECT 1" in run.result_text
    assert run.cost_usd == 0.01 and run.ok

def test_parse_stream_json_survives_non_json_noise():
    run = parse_stream_json('warning: something\n{"type":"result","is_error":false,'
                            '"result":"SELECT 1","duration_ms":10}')
    assert run.result_text == "SELECT 1"
```

- [ ] **Step 2: Run — expect ModuleNotFoundError**

- [ ] **Step 3: Implement `claude/prompts.py`**

`SYSTEM_PROMPT` follows §15: generate SQL for a local synthetic PostgreSQL database; Wren is available over MCP; consult its MDL, `get_instructions` and `recall_queries` before writing SQL; **do not execute the SQL; do not request or return database rows**; reply with a single JSON object `{"sql": "..."}` and nothing else. It names no Wren tool that this build has not verified exists.

- [ ] **Step 4: Implement `claude/cli.py`**

`detect_claude` runs `claude --version` and returns the resolved path or `None` with an actionable message. `build_command` assembles the flag list from Task 4's helpers. `ask_claude` runs it via `subprocess.run(..., timeout=...)`, kills the process tree on timeout, and never puts secrets in `env`. `parse_stream_json` tolerates non-JSON lines, collects `tool_use` names in order, and reads the terminating `result` event.

- [ ] **Step 5: Run tests — expect PASS**

---

## Task 7: Evaluator and failure classifier

**Files:**
- Create: `benchmark/evaluator.py`, `benchmark/classify.py`
- Test: `tests/test_evaluator.py`, `tests/test_classify.py`

**Interfaces:**
- Produces: `compare_results(expected: QueryResult, actual: QueryResult, ordered: bool) -> bool`; `normalize_value(v) -> Any`; `classify_failure(result: QuestionResult) -> str`.

- [ ] **Step 1: Write the failing evaluator tests**

```python
# tests/test_evaluator.py
from benchmark.evaluator import compare_results
from benchmark.models import QueryResult
from decimal import Decimal
from datetime import date

def R(cols, rows):
    return QueryResult(columns=cols, rows=rows, duration_ms=1.0, error=None, sqlstate=None)

def test_row_order_ignored_when_not_ordered():
    assert compare_results(R(["a"], [(1,), (2,)]), R(["a"], [(2,), (1,)]), ordered=False)

def test_row_order_enforced_when_ordered():
    assert not compare_results(R(["a"], [(1,), (2,)]), R(["a"], [(2,), (1,)]), ordered=True)

def test_column_order_and_alias_ignored():
    assert compare_results(R(["name","n"], [("a",1)]), R(["cnt","who"], [(1,"a")]), ordered=False)

def test_decimal_and_float_compare_equal():
    assert compare_results(R(["x"], [(Decimal("2.0"),)]), R(["x"], [(2.0,)]), ordered=False)

def test_date_and_iso_string_compare_equal():
    assert compare_results(R(["d"], [(date(2026,1,2),)]),
                           R(["d"], [("2026-01-02",)]), ordered=False)

def test_null_distinct_from_empty_string_and_zero():
    assert not compare_results(R(["x"], [(None,)]), R(["x"], [("",)]), ordered=False)
    assert not compare_results(R(["x"], [(None,)]), R(["x"], [(0,)]), ordered=False)

def test_duplicate_rows_are_significant():
    assert not compare_results(R(["a"], [(1,), (1,)]), R(["a"], [(1,)]), ordered=False)

def test_column_count_mismatch_fails():
    assert not compare_results(R(["a"], [(1,)]), R(["a","b"], [(1,2)]), ordered=False)

def test_empty_results_match():
    assert compare_results(R(["a"], []), R(["b"], []), ordered=False)
```

- [ ] **Step 2: Write the failing classifier tests**

```python
# tests/test_classify.py
from benchmark.classify import classify_failure
from benchmark.models import QuestionResult

def make(**kw):
    base = dict(sql_valid=True, execution_success=True, result_match=False,
                generated_sql="SELECT 1", expected_sql="SELECT 1",
                sqlstate=None, timed_out=False, cli_ok=True,
                parse_strategy="json", tools_used=[], category="A", tags=[])
    base.update(kw); return QuestionResult(**base)

def test_timeout_wins():
    assert classify_failure(make(timed_out=True)) == "TIMEOUT"

def test_cli_failure():
    assert classify_failure(make(cli_ok=False)) == "CLI_FAILURE"

def test_parser_failure():
    assert classify_failure(make(parse_strategy="none")) == "PARSER_FAILURE"

def test_unsafe_sql_is_invalid():
    assert classify_failure(make(sql_valid=False)) == "INVALID_SQL"

def test_undefined_table_sqlstate():
    assert classify_failure(
        make(execution_success=False, sqlstate="42P01")) == "WRONG_TABLE"

def test_undefined_column_sqlstate():
    assert classify_failure(
        make(execution_success=False, sqlstate="42703")) == "WRONG_COLUMN"

def test_grouping_error_sqlstate():
    assert classify_failure(
        make(execution_success=False, sqlstate="42803")) == "WRONG_GROUPING"

def test_owner_assignee_confusion_is_business_rule():
    r = make(tags=["semantic"],
             expected_sql="SELECT * FROM workflows w JOIN users u ON u.id=w.owner_user_id",
             generated_sql="SELECT * FROM tasks t JOIN users u ON u.id=t.assigned_user_id")
    assert classify_failure(r) in {"WRONG_BUSINESS_RULE", "SEMANTIC_MISUNDERSTANDING"}

def test_missing_join_detected():
    r = make(expected_sql="SELECT u.full_name FROM users u JOIN tasks t "
                          "ON t.assigned_user_id=u.id",
             generated_sql="SELECT full_name FROM users")
    assert classify_failure(r) == "MISSING_JOIN"

def test_unexplained_mismatch_is_honest_default():
    assert classify_failure(make()) == "RESULT_MISMATCH"
```

- [ ] **Step 3: Run both — expect ModuleNotFoundError**

- [ ] **Step 4: Implement `benchmark/evaluator.py`**

`normalize_value` maps `Decimal`→`float` (compared with `math.isclose`, rel_tol 1e-9), `date`/`datetime`→ISO string, `None`→a unique `NULL` sentinel object, `bool`→`bool` (checked before `int`, since `bool` is an `int` subclass). `compare_results` returns False on column-count mismatch, otherwise tries each permutation of the actual columns (capped at 8 columns; beyond that fall back to positional) and returns True if any permutation matches — as a sequence when `ordered`, else as a `Counter` multiset.

- [ ] **Step 5: Implement `benchmark/classify.py`**

Strictly ordered: `TIMEOUT` → `CLI_FAILURE` → `WREN_FAILURE` → `PARSER_FAILURE` → `INVALID_SQL` → SQLSTATE map → sqlglot AST diff → `RESULT_MISMATCH`. Every heuristic branch carries a comment naming it as heuristic, mirrored in `docs/` and the report.

- [ ] **Step 6: Run both test files — expect PASS**

---

## Task 8: Benchmark questions and ground-truth verification

**Files:**
- Create: `benchmark/questions.yaml`, `scripts/verify_ground_truth.py`
- Test: `tests/test_ground_truth.py`

**Interfaces:**
- Produces: `load_questions() -> list[Question]`; `Question(id, category, question, expected_sql, ordered: bool, tags: list[str], interpretation: str | None)`.

- [ ] **Step 1: Write `benchmark/questions.yaml`**

~80 questions across categories A–S per §13. Every entry has `id` (`A01`…`S05`), `category`, `question`, `expected_sql`, `ordered`. Categories R and S additionally carry `interpretation` documenting the intended reading, and are tagged `semantic`. Category L questions are tagged `date`.

- [ ] **Step 2: Write the failing tests**

```python
# tests/test_ground_truth.py
import collections, pytest
from benchmark.runner import load_questions
from database.connection import run_readonly

QS = load_questions()

def test_question_count_and_id_uniqueness():
    assert len(QS) >= 78
    assert len({q.id for q in QS}) == len(QS)

def test_all_categories_present():
    cats = {q.category for q in QS}
    assert cats == set("ABCDEFGHIJKLMNOPQRS")

def test_semantic_questions_document_interpretation():
    for q in QS:
        if q.category in ("R", "S"):
            assert q.interpretation, f"{q.id} missing interpretation"

def test_ordered_flag_set_where_question_demands_order():
    for q in QS:
        if any(w in q.question.lower() for w in
               ("newest", "highest", "alphabetically", "top ", "sorted")):
            assert q.ordered, f"{q.id} should be ordered"

@pytest.mark.integration
def test_every_expected_sql_executes(settings):
    failures = []
    for q in QS:
        r = run_readonly(settings, q.expected_sql, 15000)
        if r.error:
            failures.append((q.id, r.error))
    assert not failures, failures

@pytest.mark.integration
def test_expected_results_are_mostly_non_empty(settings):
    empty = [q.id for q in QS
             if not run_readonly(settings, q.expected_sql, 15000).rows]
    assert len(empty) <= 2, f"too many vacuous questions: {empty}"
```

- [ ] **Step 3: Implement `scripts/verify_ground_truth.py`**

Executes every `expected_sql`, prints a per-question PASS/FAIL table, and **exits non-zero if any query fails** so benchmark setup halts (§14).

- [ ] **Step 4: Run it — every query must pass before continuing**

---

## Task 9: Runner and report

**Files:**
- Create: `benchmark/runner.py`, `benchmark/report.py`
- Test: `tests/test_report.py`

**Interfaces:**
- Consumes: everything above.
- Produces: `run_question(q, config_name, privacy_mode, settings) -> QuestionResult`; `run_benchmark(questions, config_name, privacy_mode, settings) -> list[QuestionResult]`; `write_reports(results, out_dir) -> None`; `summarize(results) -> dict`.

- [ ] **Step 1: Write the failing report test**

```python
# tests/test_report.py
import json, csv
from benchmark.report import summarize, write_reports
from benchmark.models import QuestionResult

def make(qid, cat, gen, exe, match):
    return QuestionResult(question_id=qid, category=cat, question="q",
        expected_sql="SELECT 1", generated_sql="SELECT 1" if gen else None,
        sql_valid=gen, execution_success=exe, result_match=match,
        parse_strategy="json" if gen else "none", tools_used=[], tags=[],
        claude_time_ms=1.0, sql_execution_time_ms=1.0, total_time_ms=2.0,
        error=None, sqlstate=None, timed_out=False, cli_ok=True,
        failure_category=None if match else "RESULT_MISMATCH")

RESULTS = [make("A01","A",True,True,True), make("A02","A",True,True,False),
           make("B01","B",True,False,False), make("B02","B",False,False,False)]

def test_summary_counts_are_computed_not_fabricated():
    s = summarize(RESULTS)
    assert s["total"] == 4
    assert s["sql_generated"] == 3
    assert s["sql_executable"] == 2
    assert s["result_match"] == 1
    assert round(s["result_accuracy_pct"], 2) == 25.00

def test_per_category_breakdown():
    s = summarize(RESULTS)
    assert s["by_category"]["A"]["result_match"] == 1
    assert s["by_category"]["A"]["total"] == 2
    assert s["by_category"]["B"]["result_match"] == 0

def test_writes_all_three_report_files(tmp_path):
    write_reports(RESULTS, tmp_path)
    assert json.loads((tmp_path/"latest.json").read_text())["summary"]["total"] == 4
    assert len(list(csv.DictReader(
        (tmp_path/"latest.csv").open(encoding="utf-8")))) == 4
    assert "RESULT ACCURACY" in (tmp_path/"latest.md").read_text().upper()

def test_summary_of_empty_run_does_not_divide_by_zero():
    s = summarize([])
    assert s["total"] == 0 and s["result_accuracy_pct"] == 0.0
```

- [ ] **Step 2: Run — expect ModuleNotFoundError**

- [ ] **Step 3: Implement `benchmark/runner.py`**

`run_question`: build prompt → `ask_claude` → `parse_sql` → `assert_read_only` → execute generated SQL → execute `expected_sql` **in the same moment** → `compare_results` → `classify_failure` on mismatch. Records every §19 field plus raw Claude output. Results are appended to a JSONL file as they complete so a long run is resumable and inspectable mid-flight.

- [ ] **Step 4: Implement `benchmark/report.py`**

`summarize` computes totals, three rates and a per-category breakdown from the actual records only. `write_reports` emits `latest.json` (summary + full records), `latest.csv` (one row per question), and `latest.md` in the §21 layout plus a per-category table, a failure-category histogram, and a standing note that scores carry run-to-run variance and that classification beyond the deterministic signals is heuristic.

- [ ] **Step 5: Run tests — expect PASS**

---

## Task 10: Scripts

**Files:**
- Create: `scripts/check_environment.py`, `scripts/setup_demo.py`, `scripts/run_single.py`, `scripts/run_benchmark.py`

- [ ] **Step 1: Implement `scripts/check_environment.py`**

Checks Python ≥ 3.11, `psycopg` import, PostgreSQL reachability and the three tables' row counts, `wren --version`, the four Wren project configs validate, `wren memory status` backend, `claude --version`, and whether Claude auth appears configured — reporting only a boolean, never a token. Each failure prints an actionable fix.

- [ ] **Step 2: Implement `scripts/setup_demo.py`**

Applies schema + seed, creates the read-only role, builds the four Wren configs, loads memory, then runs `verify_ground_truth`. Halts on the first failure.

- [ ] **Step 3: Implement `scripts/run_single.py`**

`python scripts/run_single.py "Which workflow has the most tasks?"` with `--config`, `--privacy`, `--model`. Prints the §22 layout: QUESTION / CLAUDE / WREN-MCP tools used / GENERATED SQL / POSTGRES / RESULT / EXPECTED / MATCH, and on failure the classification and the raw Claude output. Accepts a question id (`R03`) as well as free text; free-text questions run without an expected-result comparison.

- [ ] **Step 4: Implement `scripts/run_benchmark.py`**

`--config A,B,C,D` (default `D`), `--privacy strict|validated`, `--subset N`, `--categories`, `--resume`, `--out`. Default run is full 80 on D; `--subset 25` gives the stratified fixed-seed subset for A/B/C.

- [ ] **Step 5: Run `check_environment.py` — expect all green**

---

## Task 11: Documentation

**Files:**
- Create: `README.md`, `docs/architecture.md`, `docs/data-flow.md`, `docs/privacy.md`, `docs/v2-chat-context.md`

- [ ] **Step 1: Write `docs/privacy.md`**

A table per §27 for each hop — Python→Claude, Claude→Wren, Wren→Claude, Python→PostgreSQL, PostgreSQL→Python — naming exactly what crosses it, split into metadata / schema / descriptions / business rules / questions / generated SQL / actual rows / query results. States the verified `no_connect` gating with the source reference, distinguishes Wren's **setup-time** catalog read (`wren context init`) from **benchmark-time** behaviour, and flags `run_sql`/`query_cube` explicitly as the tools that *would* expose rows and how they are blocked in each mode. Makes no unverifiable guarantee.

- [ ] **Step 2: Write `docs/architecture.md`**

Component responsibilities; the current planner/query-builder system vs what is being evaluated; and precisely which existing pieces Wren could replace and which it could not.

- [ ] **Step 3: Write `docs/data-flow.md`**

The end-to-end trace for a single question, including the exact `claude` command and the MCP handshake.

- [ ] **Step 4: Write `docs/v2-chat-context.md`**

Design only, explicitly not implemented: `session_id`, `conversation_history`, previous SQL, previous result entities, entity-reference resolution for "them", and the named extension point in `runner.py` where it would attach.

- [ ] **Step 5: Write `README.md`**

All 20 §31 sections, with the exact commands verified during this build — real versions, real flags, no invented syntax.

---

## Task 12: End-to-end verification

- [ ] **Step 1: `pytest -m "not integration"` — all green**
- [ ] **Step 2: `pytest -m integration` — all green**
- [ ] **Step 3: `python scripts/check_environment.py` — all green**
- [ ] **Step 4: `python scripts/verify_ground_truth.py` — exit 0**
- [ ] **Step 5: One live `run_single.py` in `strict` on config D — full §22 output, PASS**
- [ ] **Step 6: Confirm the §34 checklist items 1–18 all hold; report honestly on anything that does not.**

---

## Self-Review

**Spec coverage.** §2 no-Docker → global constraints; §3 architecture → Tasks 4/6/9; §4 Claude CLI → Task 6; §5 Wren MCP → Task 4; §6 privacy → Tasks 4/6 + Task 11 Step 1; §7 structure → File Structure (with the `wren_setup/` deviation); §8–9 DB → Task 2; §10–12 metadata → Task 3; §13 questions → Task 8; §14 ground truth → Task 8 Steps 3–4; §15 prompt → Task 6 Step 3; §16 parser → Task 5; §17 safety → Task 5; §18 execution → Task 2 Step 5; §19 evaluation → Task 7; §20 classification → Task 7; §21 report → Task 9; §22 single mode → Task 10 Step 3; §23 env check → Task 10 Step 1; §24 config → Task 1; §25 no planner → global constraints; §26 experiments → Task 4; §27–28 docs → Task 11; §29 V2 → Task 11 Step 4; §30 tests → Tasks 2/3/5/7/8/9; §31 README → Task 11 Step 5; §33 simplicity → flat modules, no framework; §34 → Task 12.

**Placeholders.** None: every test step carries runnable code, and every implementation step names the concrete mechanism.

**Type consistency.** `QueryResult(columns, rows, duration_ms, error, sqlstate)` is used identically in Tasks 2, 7 and 9. `ParsedSQL(sql, strategy, raw)` in Tasks 5 and 9. `ClaudeRun` fields in Tasks 6 and 9. `Question(id, category, question, expected_sql, ordered, tags, interpretation)` in Tasks 8 and 9. `DISALLOWED_TOOLS` is defined once in `wren_setup/mcp_config.py` and imported by Tasks 5 and 6.

**Known gap.** Task 2 cannot run until a working PostgreSQL password is present in `.env`. Tasks 1, 3 (authoring), 5, 6, 7, 9 and 11 are all unblocked.
