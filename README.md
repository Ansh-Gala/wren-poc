# Wren AI + Claude Code CLI + PostgreSQL — Text-to-SQL evaluation POC

A benchmark that measures how reliably **Claude Code CLI + Wren AI** generate
correct PostgreSQL for a small, semantically rich schema — while keeping actual
database rows out of the LLM.

This is a research/evaluation POC, not a production application. It exists to
answer one question with evidence:

> Can Claude Code + Wren AI reliably handle SQL planning and query generation
> for our kind of database, using our descriptions, business rules and 50–80
> examples, while keeping database rows out of the LLM interaction?

No Docker. No Anthropic API. No custom SQL planner in Python.

---

## 1. Why we are evaluating Wren

Our real system has five flat tables, table/column descriptions, business
meanings, 50–80 example questions, and an LLM planner feeding a **custom query
builder** that has not worked reliably enough.

The proposal is to replace the schema-knowledge and query-generation parts with
Claude Code + Wren's semantic layer, and keep the rest on our side. This POC
measures whether that would work, and what it costs.

See [docs/architecture.md](docs/architecture.md) for which of our components
Wren could and could not replace.

## 2. Architecture

```
Python  ──subprocess──▶  Claude Code CLI  ──MCP/stdio──▶  wren serve mcp
                                                               │
                                          MDL · rules · glossary · exemplars
                                                               │
                                                     Generated SQL
                                                               │
Python: parse → read-only gate → PostgreSQL → rows → evaluator
                                                               │
                                              rows STOP here, never sent back
```

Python orchestrates, executes and scores. **It never decides how SQL should be
constructed** — that is entirely Claude + Wren.

## 3. PostgreSQL schema

Three tables, 22 columns, workflow/task domain.

```
users(id, full_name, email, department, role, status)
workflows(id, name, description, category, status, owner_user_id,
          created_at, updated_at)
tasks(id, workflow_id, name, description, status, priority,
      assigned_user_id, due_date, completed_at, created_at)

workflows.owner_user_id  → users.id      (the workflow OWNER)
tasks.workflow_id        → workflows.id
tasks.assigned_user_id   → users.id      (the task ASSIGNEE, nullable)
```

The owner/assignee distinction is deliberate: it is the schema's main trap and
several questions exist purely to test whether the semantic layer prevents the
confusion.

Synthetic data: 15 users, 8 workflows, 50 tasks. Deterministic (fixed ids,
literal rows). Dates are relative to `CURRENT_DATE` so "overdue" and "due
today" are never empty. All `@example.invalid` addresses (RFC 2606 — cannot
resolve).

## 4. Semantic metadata

`metadata/schema_description.yaml` — every table and column documented by
**business meaning**, not restated names, with enum semantics:

```yaml
users.status: >-
  ACTIVE: the user is available and may receive new task assignments.
  INACTIVE: the user is unavailable and must not receive new assignments;
  they may still appear as the assignee of historical tasks...
```

Plus `terminology`, `relationships` and an `ambiguities` section.

## 5. Business rules

`metadata/business_rules.yaml` — 23 rules, each with a prose definition and a
SQL fragment. Rules that would not change any benchmark answer were left out
deliberately; padding the file would flatter configuration C without teaching
anything.

Compiled into `knowledge/rules/general.md`, served by `get_instructions`.

## 6. Question–SQL examples

`metadata/question_sql_pairs.yaml` — 17 confirmed NL→SQL pairs in Wren's native
format (`version: 1`, `pairs: [{nl, sql}]`), loaded with `wren memory load` into
LanceDB-backed query memory and retrieved semantically by `recall_queries`.

**They are disjoint from the benchmark questions**, enforced by a test —
otherwise configuration D would measure memorisation, not generalisation.

## 7. Claude Code CLI integration

`subprocess` on the local `claude` binary. No Anthropic SDK, no
`ANTHROPIC_API_KEY` (it is actively removed from the child environment).
Authentication stays inside the local Claude Code install.

The exact command is in [docs/data-flow.md](docs/data-flow.md#2-python-invokes-claude-code).

## 8. Wren MCP integration

`wren serve mcp --transport stdio --project <config> [--no-connect]`, spawned by
Claude Code from a generated `--mcp-config` file, with `--strict-mcp-config` so
no other MCP server on the machine can leak in.

Tools used: `get_mdl`, `list_models`, `describe_model`, `describe_schema`,
`get_data_source`, `list_functions`, `get_instructions`, `recall_queries`,
`get_context`, `list_stored_queries`, `list_knowledge`, `dry_plan`, and
`dry_run` in connected mode only.

**Important:** this uses the Apache-2.0 MCP server built into the `wrenai` PyPI
package. The separate `Canner/WrenAI-mcp` repo is a cloud/Enterprise connector
requiring OAuth against `cloud.getwren.ai` and is **not** used.

See [docs/wren-findings.md](docs/wren-findings.md) for everything verified about
Wren's actual behaviour, including three bugs/gotchas.

## 9. Privacy

Rows never reach Claude. In `strict` mode this is structural, not a policy:
`--no-connect` means `run_sql` and `query_cube` are **never registered as MCP
tools** and Wren opens no database connection at all. Verified over the wire by
`scripts/check_environment.py`.

Full boundary-by-boundary account, plus a hole we found and closed, in
[docs/privacy.md](docs/privacy.md). Read that one — it documents a real failure
where Wren silently died and Claude answered using Bash instead.

## 10. Installation

Requires Python 3.11+, PostgreSQL 14+, and Claude Code CLI already installed
and signed in.

```bash
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements.txt   # Windows
# source .venv/bin/activate && pip install -r requirements.txt  # macOS/Linux
```

`requirements.txt` pins **`mcp<2`**. This is not optional — see §Known
limitations.

## 11. Configuration

```bash
cp .env.example .env
```

Set `DATABASE_PASSWORD` (PostgreSQL owner) and keep
`DATABASE_READONLY_PASSWORD`. There is deliberately no `ANTHROPIC_API_KEY`.

Useful knobs: `CLAUDE_MODEL` (blank = CLI default = Opus; `sonnet` is ~2×
cheaper and ~2× faster), `BENCHMARK_CONFIG` (A/B/C/D),
`BENCHMARK_PRIVACY_MODE` (`strict`/`validated`), `WREN_MEMORY_BACKEND`.

## 12. Setup

```bash
createdb wren_demo                              # if it does not exist
python scripts/setup_demo.py                    # schema, seed, read-only role
python scripts/build_wren.py                    # the four Wren configurations
python scripts/verify_ground_truth.py           # must pass before benchmarking
python scripts/check_environment.py             # everything, end to end
```

`check_environment.py` should print all `ok`, ending with:

```
[ok] Wren MCP / strict     14 tools, no row-returning tools registered
[ok] Wren MCP / validated  17 tools, row-returning present: ['run_sql', 'query_cube']
[ok] benchmark questions   86 across 19 categories (ABCDEFGHIJKLMNOPQRS)
```

## 13. Single-question mode

The most useful mode for studying Wren, because it shows which MCP tools were
actually called:

```bash
python scripts/run_single.py R06                       # by question id
python scripts/run_single.py "Which workflow has the most tasks?"
python scripts/run_single.py R06 --config A --privacy validated --show-raw
```

## 14. Full benchmark

```bash
python scripts/run_benchmark.py                          # 86 questions, config D
python scripts/run_benchmark.py --subset 19              # one per category (smoke)
python scripts/run_benchmark.py --config A,B,C --subset 25   # knowledge lift
python scripts/run_benchmark.py --categories R,S         # semantics only
python scripts/run_benchmark.py --resume                 # continue an interrupted run
```

Results stream to `results/raw/<config>.<privacy>.jsonl` as each question
finishes, so a long run is watchable and resumable.

Measured on Sonnet 5, warm cache: **~$0.13 and 16–25 s per question**
(≈$11 and ~25 min for the full 86).

## 15. Reading the results

`results/latest.md` — human report; `latest.json` — full records including raw
Claude output; `latest.csv` — one row per question.

Three headline numbers, all computed from actual records:

```
SQL generated:     n / N     did anything parseable come back
SQL executable:    n / N     did PostgreSQL accept it
Correct results:   n / N     did it return the right rows
```

Plus per-category accuracy and a failure histogram.

**Two accuracy metrics.** Strict result match requires the same columns. A
second, column-tolerant metric records whether the right *rows* were selected
even when extra columns came back — because several questions genuinely do not
specify which columns to return. Reporting both keeps real logic errors
separate from column-selection ambiguity.

## 16. Debugging a failure

1. Find the question id in `results/latest.md`.
2. Re-run it alone: `python scripts/run_single.py <id> --show-raw`.
3. Check the "WREN / MCP" section. **If no Wren tools were called, the semantic
   layer contributed nothing** and the result says nothing about Wren.
4. Compare the generated and expected SQL in the report.

Failure categories split into **deterministic** (timeout, CLI failure, Wren
tool error, parser miss, safety rejection, PostgreSQL SQLSTATE) and
**heuristic** (everything inferred from an AST diff). The report labels which
is which. Do not read heuristic categories as ground truth about *why* the
model failed.

## 17. Knowledge experiment

| Config | Schema | Descriptions | Business rules | NL→SQL exemplars |
|---|---|---|---|---|
| A | yes | — | — | — |
| B | yes | yes | — | — |
| C | yes | yes | yes | — |
| D | yes | yes | yes | yes (17, LanceDB) |

The A→D delta is the number that tells you whether porting your existing
descriptions and 50–80 examples into Wren would pay for itself.

## 18. Tests

```bash
.venv/Scripts/python.exe -m pytest -m "not integration"   # fast, no services
.venv/Scripts/python.exe -m pytest                        # includes live DB
```

## 19. Known limitations

- **`mcp<2` is mandatory.** wrenai 0.13.4 declares `mcp>=1.19` but its code
  imports `mcp.server.fastmcp.FastMCP`, which mcp 2.x renamed. With mcp 2.x the
  Wren MCP server **dies on import, Claude Code reports nothing**, and the
  benchmark silently measures Claude alone. `check_environment.py` checks for
  this explicitly.
- **`PYTHONUTF8=1` is required on Windows.** wrenai 0.13.4 writes UTF-8 without
  an explicit encoding (`context_cli.py:359`), crashing under cp1252. Set in
  every `wren` subprocess.
- **Wren needs a connection profile even in `strict` mode**, or it exits with
  `'datasource' key not found in connection info` — it still needs to know the
  SQL dialect. The profile holds read-only credentials only.
- **No database introspection.** `wren context import` supports dbt only in
  0.13.4, so MDL is authored from our YAML rather than introspected.
- **`--allowedTools` does not restrict anything** — it only pre-approves. All 18
  built-in tools are explicitly denied instead.
- **Agentic runs are non-deterministic.** The same question can pass in one run
  and fail in the next. Repeat before treating a few points as meaningful.
- **Failure classification beyond the deterministic signals is heuristic.**
- **`validated` mode's guarantee is enforcement, not impossibility.** Only
  `strict` is structural.
- **V2 multi-turn is designed, not built** — see
  [docs/v2-chat-context.md](docs/v2-chat-context.md).
- **Three tables, not five.** The POC schema is smaller than the real system,
  though it was shaped to include the same failure modes.

## 20. Layout

```
config/       settings (frozen dataclass), redacting logger
database/     schema.sql, seed.sql, connection, setup
metadata/     schema_description · business_rules · question_sql_pairs  (source of truth)
wren_setup/   build the 4 configs, mcp config, preflight guard
claude/       CLI wrapper, prompts, 5-strategy SQL parser
benchmark/    questions.yaml, runner, evaluator, classifier, report, safety
scripts/      setup_demo · build_wren · verify_ground_truth · check_environment
              run_single · run_benchmark
docs/         architecture · data-flow · privacy · v2-chat-context · wren-findings
results/      latest.{json,csv,md}, raw/*.jsonl
```
