# Wren AI + Claude Code CLI + PostgreSQL — Text-to-SQL Evaluation POC

**Date:** 2026-09-04
**Status:** Design — awaiting approval
**Goal:** Answer one question with evidence: *can Claude Code CLI + Wren AI reliably do SQL
planning/generation for a small, flat, semantically-rich schema, while keeping database rows out
of the LLM interaction?*

---

## 1. Verified facts (research, not assumption)

All of the following was read from the shipped `wrenai` 0.13.4 wheel and the locally installed
`claude` 2.1.234 — not from marketing docs.

### 1.1 There are two different "Wren MCP" products

| | `Canner/WrenAI-mcp` | `wrenai` PyPI package |
|---|---|---|
| Endpoint | `https://cloud.getwren.ai/api/mcp` | local stdio / http |
| Auth | OAuth, org admin must enable | none |
| Licence | **Enterprise / cloud-only** | Apache-2.0 |
| Docker | n/a | **not required** |
| Verdict | ✗ violates §2 and §6 | ✓ **this is what we use** |

Install: `pip install 'wrenai[postgres,mcp,memory]'` → console script `wren` (Typer app,
entry point `wren.cli:app`). Requires Python ≥ 3.11; local Python is 3.12.6. ✓

### 1.2 Actual Wren MCP tools (`wren/mcp_server.py`)

| Group | Tools | Returns DB rows? |
|---|---|---|
| Context | `get_mdl`, `list_models`, `describe_model`, `describe_schema`, `get_data_source`, `list_functions`, `list_cubes`, `describe_cube` | No |
| Knowledge | `get_instructions`, `recall_queries`, `get_context`, `list_stored_queries`, `list_knowledge` | No |
| SQL | `dry_plan` (MDL → dialect SQL, **no DB connection**) | No |
| SQL | `dry_run` (validate against live DB, returns `{"ok": true}`) | No |
| SQL | `run_sql` | **YES** ⚠ |
| SQL | `query_cube` | **YES** ⚠ |
| Write | `store_query` (only with `--allow-write`) | No |

Resources: `wren://mdl`, `wren://instructions`, `wren://project`, `wren://agents`,
`wren://knowledge/{path}`. Prompt: `wren_workflow`.

### 1.3 The privacy control is real and code-level

```python
def _register_query_tools(mcp, ctx):
    if not ctx.no_connect:          # <-- gates run_sql, dry_run, query_cube
        @mcp.tool() def run_sql(...)
        @mcp.tool() def dry_run(...)
        @mcp.tool() def query_cube(...)
    @mcp.tool() def dry_plan(...)   # <-- outside the gate, always available
```

With `wren serve mcp --no-connect`, `run_sql` and `query_cube` are **never registered as MCP
tools** and Wren **never opens a database connection** (`conn_required=not no_connect` in
`serve_cli.py`). This is a structural guarantee, not a policy. `dry_plan` survives and still
expands MDL SQL to PostgreSQL dialect.

### 1.4 Wren project layout and CLI

Env vars: `WREN_HOME`, `WREN_PROJECT_HOME`, `WREN_MEMORY_DIR`, `WREN_MEMORY_BACKEND`,
`WREN_DATASOURCE`, `WREN_DB_STATEMENT_TIMEOUT`, `WREN_EMBEDDING_MODEL`.

Project files: `config.yml`, `mdl.json`, `instructions.md`, `profiles.yml`, `queries.yml`,
`knowledge/`.

Commands used: `wren context init|build|validate|show|instructions`,
`wren memory load|index|recall|status|list`, `wren serve mcp`, `wren dry-plan`, `wren dry-run`.

`wren memory load <file.yaml>` natively ingests a YAML document with a top-level `pairs:` key —
this is exactly §12's `question_sql_pairs.yaml`, no adapter needed.

`recall_queries` backend selection: `WREN_MEMORY_BACKEND=grep|lancedb`; `lancedb` is used when
the `memory` extra is installed, else it silently downgrades to `grep`. **Decision: install the
`memory` extra and use `lancedb`**, because our real system's 50–80 examples would be retrieved
semantically, and a `grep` backend would unfairly understate Experiment D.

### 1.5 Claude Code CLI 2.1.234 — confirmed flags

`-p/--print`, `--output-format text|json|stream-json`, `--verbose`, `--mcp-config`,
`--strict-mcp-config`, `--allowedTools`, `--disallowedTools`, `--permission-mode`, `--model`,
`--system-prompt`, `--append-system-prompt`, `--max-budget-usd`.

Authentication stays entirely inside the local Claude Code install. No Anthropic SDK, no
`ANTHROPIC_API_KEY`, no HTTP to Anthropic anywhere in this project.

### 1.6 Local machine state

Python 3.12.6 ✓ · PostgreSQL 16.12 accepting connections on 5432 ✓ · `claude` 2.1.234 ✓ ·
`wren` not installed (Phase 0) · `uv` not installed → use `pip` in a project venv.

**Open input needed:** PostgreSQL uses password auth (scram) and there is no `~/.pgpass`. I need
a working superuser credential placed in `.env` to create and seed `wren_demo`. I will read it
from `.env` and never echo it.

---

## 2. Architecture

```
                        Python (orchestrator)
                                │
                                │ subprocess: claude -p --mcp-config ... --strict-mcp-config
                                ▼
                        Claude Code CLI  (local auth, no API key)
                                │
                                │ MCP over stdio
                                ▼
                    wren serve mcp  [--no-connect]
                                │
                 ┌──────────────┴───────────────┐
                 │                              │
         mdl.json / instructions.md      dry_plan / dry_run
         queries.yml (lancedb recall)    (SQL only, never rows)
                 │                              │
                 └──────────────┬───────────────┘
                                ▼
                        Generated SQL (text)
                                │
                                ▼
                     Python: parse → safety-gate
                                │
                                ▼
                  PostgreSQL  (read-only role, READ ONLY txn)
                                │
                                ▼
                          Result rows
                                │
                                ▼
                        Python evaluator  ── rows NEVER return to Claude
```

**Division of labour.** Claude Code is the agent/LLM. Wren is the semantic layer, schema
knowledge, business rules and exemplar retrieval, and it emits the SQL. Python only orchestrates,
executes and scores. **No Python planner, query builder or SQL reasoning of any kind** (§25). The
only SQL Python authors is the hand-written ground truth, which is fixture data, not a planner.

### 2.1 Two privacy configurations, both benchmarked

| | `strict` (default) | `validated` |
|---|---|---|
| Wren launch | `wren serve mcp --no-connect` | `wren serve mcp` |
| DB connection from Wren | none | read-only role `wren_ro` |
| `run_sql` / `query_cube` | not registered | registered, denied at CLI |
| `dry_run` available | no | yes |
| Guarantee | structural (code) | enforcement (CLI deny + PG grants) |

`validated` additionally passes
`--disallowedTools mcp__wren__run_sql mcp__wren__query_cube` and connects Wren through a
PostgreSQL role with `SELECT`-only grants. Running both quantifies what live `dry_run` validation
is actually worth — a real input to your production decision.

---

## 3. Database (§8, §9)

Three tables, 22 columns, workflow/task domain, exactly as specified in §8. FKs:
`workflows.owner_user_id → users.id`, `tasks.workflow_id → workflows.id`,
`tasks.assigned_user_id → users.id`.

Deterministic synthetic data: 15 users, 8 workflows, 50 tasks. Explicit literal `INSERT`s with
fixed IDs — no random generation — so the dataset is byte-identical between runs. Obviously
synthetic names (`Alice Anderson`, `alice.anderson@example.invalid`; `.invalid` is the RFC 2606
reserved TLD, so no address can ever resolve).

**Date handling.** Category L needs "due today", "overdue", "completed this month" to be
non-empty and stable. Dates are seeded *relative to* `CURRENT_DATE` (e.g.
`CURRENT_DATE - 5`, `date_trunc('month', CURRENT_DATE) + INTERVAL '2 days'`), chosen with margins
that stay correct across month boundaries. Consequence: ground-truth **results** are recomputed at
benchmark time rather than cached, so expected and generated SQL always execute in the same
moment against the same data.

**Tie safety.** Every "top N" / "most" question is seeded so the boundary has no tie. This is
deliberate — ties would make "correct" ambiguous and pollute the accuracy number.

Coverage guaranteed by the seed: multiple departments/roles, ACTIVE+INACTIVE users, all four task
statuses, all priorities, overdue and future tasks, NULL `completed_at`, workflows with zero
tasks, users with zero assigned tasks, owners-who-aren't-assignees, assignees-who-aren't-owners,
multiple workflows per owner, multiple tasks per workflow.

---

## 4. Semantic layer (§10, §11, §12)

Single source of truth in `metadata/`, compiled into the Wren project:

- `schema_description.yaml` — every table and every column, with **business meaning** and
  enum-value semantics (`ACTIVE: may receive new assignments`, not `status of the user`), plus
  terminology, relationship semantics, and an explicit ambiguity section covering the
  owner-vs-assignee trap.
- `business_rules.yaml` — active user, completed/open/overdue task, owner vs assignee joins,
  `COUNT(tasks.id)` vs `COUNT(DISTINCT workflows.id)` after a join, and more. Compiled to
  Wren's `instructions.md`.
- `question_sql_pairs.yaml` — the nine confirmed examples from §12 plus enough to reach a
  realistic corpus, in Wren's native `pairs:` format. **Every pair's SQL is executed against
  PostgreSQL and must succeed before it is loaded.** Loaded via `wren memory load`.

These pairs are **disjoint from the benchmark questions** — no exemplar may be a benchmark
question, or Experiment D would be measuring memorisation instead of generalisation. This is
enforced by a test.

### 4.1 The four knowledge configurations (§26)

Built as four sibling Wren project directories, selected per-run through `WREN_PROJECT_HOME` /
`WREN_MEMORY_DIR` in the MCP server's `env` block:

| Config | mdl.json | instructions.md | memory |
|---|---|---|---|
| A | raw introspected schema (no descriptions) | absent | empty |
| B | + column/table descriptions | absent | empty |
| C | + descriptions | business rules | empty |
| D | + descriptions | business rules | loaded (lancedb) |

Base MDL comes from `wren context init` introspecting PostgreSQL — Wren stays authoritative for
schema. Because the schema carries no `COMMENT ON` statements, that raw introspection *is*
config A; B/C/D are then enriched from `schema_description.yaml`. `wren context validate` gates
each of the four.

**Note for the privacy doc:** `wren context init` is the one place Wren reads the database at
*setup* time, and it reads catalog metadata only, never rows. At *benchmark* time the `strict`
config opens no connection at all. `docs/privacy.md` will state this distinction explicitly
rather than blurring setup and runtime.

**Run scope (agreed):** full 80 questions on config D; a stratified, fixed-seed 25-question
subset on A/B/C. ~155 sessions instead of 320. `--config` and `--subset` remain available to run
the full matrix later.

---

## 5. Claude invocation (§4, §15)

```
claude -p "<question>"
  --output-format stream-json --verbose
  --mcp-config <generated>/mcp.<config>.json
  --strict-mcp-config
  --append-system-prompt "<contents of claude/prompts.py, passed inline>"
  --allowedTools mcp__wren__get_mdl mcp__wren__list_models mcp__wren__describe_model \
                 mcp__wren__describe_schema mcp__wren__get_instructions \
                 mcp__wren__recall_queries mcp__wren__get_context \
                 mcp__wren__list_stored_queries mcp__wren__list_knowledge \
                 mcp__wren__dry_plan [mcp__wren__dry_run]
  --disallowedTools mcp__wren__run_sql mcp__wren__query_cube
  --model <configurable>
```

`--strict-mcp-config` guarantees no other MCP server your machine has configured leaks into the
run. The allowlist is explicit, so Bash/Edit/Write/WebFetch are all unavailable to the subprocess.

**Why `stream-json`:** it yields the tool-call events, which gives §22 its real "Tools used" list
and lets the failure classifier distinguish a Wren MCP error from a Claude error. The terminating
`result` event supplies duration and cost.

The wrapper (`claude/cli.py`) handles: `claude` presence detection, non-interactive invocation,
stdout/stderr capture, exit code, timeout with process-tree kill, and structured return. It never
logs credentials or environment secrets.

**Prompt** instructs Claude to consult Wren's MDL, instructions and exemplars, to emit SQL only,
and explicitly **not** to execute it or return rows — reinforcing at the prompt layer what
`--no-connect` and `--disallowedTools` enforce mechanically.

---

## 6. Parsing, safety, execution (§16, §17, §18)

**Parser** — ordered strategies, each independently tested, no single fragile regex:
1. whole output parses as JSON with an `sql` key
2. last ```` ```sql ```` fenced block
3. last fenced block of any language
4. JSON object embedded in prose
5. last statement starting `SELECT`/`WITH`

Returns the SQL plus which strategy matched, so parser fragility is itself measurable.

**Safety gate** — `sqlglot` parses the statement; reject on more than one statement, or on any
DDL/DML node (`INSERT UPDATE DELETE DROP ALTER TRUNCATE CREATE GRANT REVOKE`, plus `COPY`,
`CALL`, `DO`, `MERGE`, `SET`). A regex screen backs it up. Defence in depth: a read-only
PostgreSQL role, `SET TRANSACTION READ ONLY`, and `statement_timeout`. The benchmark cannot
modify the database.

**Execution** captures rows, column names, execution time and the PostgreSQL `SQLSTATE`.

---

## 7. Evaluation (§19, §20)

Result-based, never string comparison.

Normalisation: `Decimal`/`float` compared with tolerance; `datetime`/`date` to ISO; `None` to a
sentinel distinct from `''` and `0`; `bool` canonicalised.

Comparison: if column counts differ → mismatch. Otherwise search for a column permutation under
which the results match — this makes the score independent of column order and alias naming
(Spider-style execution accuracy). Questions carry `ordered: true` when the question demands an
order; those compare as sequences, all others as multisets.

**Failure classification is heuristic and will be documented as such.** Deterministic signals
first — `PARSER_FAILURE`, `TIMEOUT`, `CLI_FAILURE`, `WREN_FAILURE` (MCP tool error in the event
stream), `INVALID_SQL` (safety reject or syntax error), then PostgreSQL SQLSTATE mapping
(`42P01` → `WRONG_TABLE`/`HALLUCINATED_SCHEMA`, `42703` → `WRONG_COLUMN`, `42803` →
`WRONG_GROUPING`). Only for queries that ran but returned the wrong rows do we fall back to a
sqlglot AST diff against the expected SQL (table set, join count, aggregate functions, predicates)
to pick `MISSING_JOIN`/`WRONG_JOIN`/`WRONG_FILTER`/`WRONG_AGGREGATION`/`WRONG_DATE_LOGIC`, with
`WRONG_BUSINESS_RULE`/`SEMANTIC_MISUNDERSTANDING` reserved for questions tagged as
semantics-dependent, and `RESULT_MISMATCH` as the honest default when nothing else is confident.

Every record stores all fields listed in §19. Raw Claude output is retained per question so any
classification can be re-examined by hand.

---

## 8. Benchmark set (§13)

~80 questions across categories A–S, each with `id`, `category`, `question`, `expected_sql`,
`ordered`, and — for categories R and S — an `interpretation` note recording the intended reading.

**Ground truth is human-authored and machine-verified** (§14): `verify_ground_truth.py` executes
every expected query; **any failure aborts benchmark setup**. Neither Wren nor Claude ever
influences ground truth.

Reports to `results/latest.{json,csv,md}` with generation / execution / accuracy rates and a
per-category breakdown, all computed from actual results. No fabricated metrics; a mediocre score
is a valid and useful outcome.

---

## 9. Deviations from the brief, and why

1. **`wren/` → `wren_setup/`.** A top-level package named `wren/` would shadow the installed
   `wren` module from the `wrenai` package on `sys.path`. Renaming avoids a genuinely nasty
   import bug. Everything else in §7's structure is kept as written.
2. **Two privacy configs instead of one**, per your decision — `strict` is the default.
3. **Ground-truth results computed at run time, not cached**, because seed dates are relative to
   `CURRENT_DATE`. The ground-truth *SQL* is still fixed and hand-verified.
4. **Reduced A/B/C run scope** to a 25-question subset, per your decision. Full matrix stays one
   flag away.
5. **`WrenAI-mcp` rejected** in favour of the OSS `wrenai` MCP server, because the former is
   cloud/Enterprise-only and would violate both the no-Docker and the privacy requirements.

## 10. Known risks, stated up front

- Agentic runs are non-deterministic; the same question can score differently across runs. The
  report will state that scores carry run-to-run variance and single runs should not be
  over-read.
- `dry_plan` in `strict` mode cannot catch every error a live `dry_run` would. This is precisely
  the cost the `strict` vs `validated` comparison is designed to measure.
- Failure classification beyond the deterministic signals is heuristic; the report labels it.
- `lancedb` + `sentence-transformers` is a several-hundred-MB install with a one-time model
  download.

## 11. Delivery plan

| Phase | Work | Verified by |
|---|---|---|
| 0 | venv, `pip install 'wrenai[postgres,mcp,memory]'`, tool detection | `wren --version`, `check_environment.py` |
| 1 | schema.sql, seed.sql, connection.py, read-only role | FK + determinism tests pass |
| 2 | the three `metadata/` YAML files | schema coverage test |
| 3 | build 4 Wren project configs | `wren context validate` × 4, `wren memory status` |
| 4 | mcp_config, claude/cli.py, prompts, parser | parser + safety unit tests |
| 5 | ~80 questions + ground truth | **all expected SQL executes** |
| 6 | runner, evaluator, classifier, report | evaluator unit tests |
| 7 | the four `scripts/` entry points | `check_environment.py` clean |
| 8 | test suite | `pytest` green |
| 9 | README + architecture/data-flow/privacy/v2 docs | — |
| 10 | end-to-end verification | one live `run_single.py` |

Per your decision, I execute phases 0–10 including a single live `run_single.py` sanity run, and
leave the ~155-session benchmark for you to launch.
