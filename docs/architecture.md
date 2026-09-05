# Architecture

## The question this POC answers

> Can Claude Code CLI + Wren AI reliably handle SQL planning and query
> generation for our kind of database — a few flat tables, rich descriptions,
> 50–80 examples — while keeping actual database rows out of the LLM?

Not "does it work at all". The interesting question is *how much of our current
custom machinery could this replace*, and *what does it cost in accuracy*.

## Components and their responsibilities

```
                         Python (benchmark/, scripts/)
                                     │
                  subprocess: claude -p --strict-mcp-config …
                                     ▼
                         Claude Code CLI (local auth)
                                     │
                            MCP over stdio
                                     ▼
                    wren serve mcp --no-connect
                    ┌────────────────┴────────────────┐
                    │                                 │
            MDL semantic model              dry_plan (MDL → dialect SQL)
            knowledge/rules/                (no database contact)
            knowledge/glossary/
            knowledge/caveats/
            query memory (LanceDB)
                    └────────────────┬────────────────┘
                                     ▼
                            Generated SQL (text)
                                     ▼
                    Python: parse → read-only safety gate
                                     ▼
                  PostgreSQL (wren_ro, READ ONLY txn)
                                     ▼
                              Result rows
                                     ▼
                          Python evaluator ── rows stop here
```

### Claude Code CLI — the agent

Provides the model and the agent loop. Invoked once per question with `-p`
(headless). It decides which Wren tools to call and in what order, then returns
SQL as JSON.

It is **not** given the schema in its prompt. Everything it knows about the
database, it must obtain from Wren. That is deliberate: it is what makes the
benchmark a measurement of the semantic layer rather than of the prompt.

Authentication stays entirely inside the local Claude Code install. No
Anthropic SDK, no API key, no HTTP to Anthropic anywhere in this project.

### Wren AI — the semantic layer

Runs as a local MCP server (`wren serve mcp`), spawned by Claude Code over
stdio. It supplies:

| Concern | Where it lives | Exposed by |
|---|---|---|
| Tables, columns, types, joins | `models/*/metadata.yml`, `relationships.yml` | `list_models`, `describe_model`, `get_mdl`, `describe_schema` |
| Business meaning of each column | `properties.description` in the model YAML | the same tools |
| Business rules | `knowledge/rules/general.md` | `get_instructions` |
| Terminology | `knowledge/glossary/terms.md` | `list_knowledge`, `get_context` |
| Ambiguities and gotchas | `knowledge/caveats/ambiguities.md` | the same |
| Confirmed NL→SQL examples | LanceDB query memory | `recall_queries` |
| SQL validation | — | `dry_plan` (and `dry_run` when connected) |

All of that content is generated from `metadata/*.yaml` by
`wren_setup/build.py`. The YAML is the source of truth; the Wren project is a
build artefact.

### Python — orchestration, execution, scoring

Python does four things and no more:

1. **Orchestrate** — invoke the CLI, one question at a time.
2. **Parse** — extract SQL from Claude's reply (`claude/parser.py`).
3. **Execute** — gate it read-only, run it against PostgreSQL.
4. **Score** — compare rows to hand-written ground truth, classify failures.

**Python contains no SQL planner, query builder or SQL reasoning.** It never
decides how a query should be constructed. The only SQL it authors is the
hand-written ground truth in `benchmark/questions.yaml`, which is fixture data —
the answer key, not a planner. This separation is the whole point: if Python
helped build the query, the benchmark would be measuring Python.

### PostgreSQL — the database

Three flat tables, deliberately shaped like the system under evaluation: few
tables, wide-ish rows, and two easily-confused user relationships (workflow
*owner* vs task *assignee*).

Generated SQL runs as `wren_ro`, a `SELECT`-only role, inside a `READ ONLY`
transaction with a statement timeout.

## What we currently have, and what Wren could replace

### Today

```
question → LLM planner → custom query builder → SQL → database
              │                   │
              │                   └── hand-written join/filter construction
              └── decides intent, tables, filters
```

The custom query builder is the part that has not worked reliably enough.

### Under evaluation

```
question → Claude Code → Wren (MDL + rules + exemplars) → SQL → database
```

### What Wren could plausibly replace

| Our component | Wren equivalent | Assessment |
|---|---|---|
| Schema knowledge passed to the LLM | MDL + `describe_model` | **Replaceable.** This is Wren's core job. |
| Table/column description store | `properties.description` | **Replaceable**, and better structured than a prompt blob. |
| Business-rule prompt text | `knowledge/rules/` | **Replaceable.** Retrieved on demand rather than always in context. |
| Example-question corpus | LanceDB query memory + `recall_queries` | **Replaceable**, and an upgrade: semantic retrieval instead of stuffing all 50–80 examples into every prompt. |
| Custom query builder | Claude + `dry_plan` | **This is the open question.** The benchmark exists to answer it. |
| SQL validation | `dry_run` | Partly. Only in connected mode, and it is a validity check, not a correctness check. |

### What Wren does *not* replace

- **Execution.** We still run the SQL ourselves — which is what keeps rows away
  from the model.
- **Correctness judgement.** `dry_run` tells you a query is *valid*, never that
  it is *right*. Ground truth remains ours.
- **The rest of the application.** Wren is a semantic layer, not a backend.
- **Ambiguity resolution.** Where a question genuinely has two readings — see
  the column-selection issue in `results/latest.md` — Wren cannot know which
  you meant. That has to be settled by the question, the rules, or a
  conversation.

## Design decisions worth knowing

**Four knowledge configurations, not one.** A/B/C/D isolate what each layer of
semantic metadata is actually worth. Since your real system already has
descriptions and 50–80 examples, the A→D delta is the number that tells you
whether porting them to Wren would pay.

**Two privacy modes.** `strict` (`--no-connect`) is structurally incapable of
returning rows; `validated` connects so Claude can use `dry_run`. Running both
quantifies what live validation buys.

**Preflight before every run.** `wren_setup/preflight.py` speaks MCP to the
server and refuses to run unless the expected tools are present. This exists
because Wren's server once failed silently and the benchmark happily measured
Claude alone — see `docs/privacy.md`.

**Ground truth is executed, never cached.** Seed dates are relative to
`CURRENT_DATE`, so expected and generated SQL are run in the same moment.

**Two accuracy metrics.** Strict result match, plus a column-tolerant "right
rows" match. Some questions genuinely do not specify which columns to return;
reporting both separates real logic errors from column-selection ambiguity
instead of silently choosing one interpretation.
