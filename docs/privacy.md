# What crosses each boundary

The requirement for this POC was: **metadata may reach the LLM; database rows
must not.** This document states exactly what travels over each connection, and
distinguishes what was *verified* from what is merely *configured*.

No claim here is made on trust. Where something is guaranteed, the guarantee is
named and the evidence given. Where it is only enforced by configuration, that
is said plainly, because configuration can be changed by accident.

---

## The five boundaries

```
   Python  ──(1) subprocess──▶  Claude Code CLI
                                      │
                                      │ (2) MCP over stdio
                                      ▼
                                 wren serve mcp
                                      │
                                      │ (3) only in `validated` mode
                                      ▼
   Python  ──(4) SELECT──────▶   PostgreSQL
   Python  ◀─(5) rows────────    PostgreSQL
```

### (1) Python → Claude Code CLI

| Sent | Not sent |
|---|---|
| The natural-language question | Any database row |
| The system prompt (`claude/prompts.py`) | Any query result |
| Paths to the MCP config file | Any password or credential |
| Tool allow/deny lists | `ANTHROPIC_API_KEY` (explicitly removed from the child environment) |

The question text comes from `benchmark/questions.yaml`. It is written by us
and contains no data values other than one deliberate reference to the
synthetic name "Carol Chen" in question N03.

Ground-truth SQL is **never** sent. Claude never sees the expected answer.

### (2) Claude Code ↔ Wren MCP server

Wren returns **metadata only**:

| Tool | Returns |
|---|---|
| `get_mdl`, `describe_schema` | table names, column names, types, relationships |
| `list_models`, `describe_model` | the same, per model, plus descriptions |
| `get_instructions` | business rules from `knowledge/rules/` |
| `recall_queries`, `list_stored_queries` | our own NL→SQL exemplars |
| `list_knowledge`, `get_context` | glossary and caveat documents |
| `dry_plan` | SQL expanded to PostgreSQL dialect — **no database contact** |
| `get_data_source` | the data-source *type* (`postgres`) |

Every one of those is content **we authored**, in `metadata/*.yaml`. None of it
is read from table rows.

Three tools *would* return rows. They are handled as follows:

| Tool | `strict` mode | `validated` mode |
|---|---|---|
| `run_sql` | **not registered** | registered, denied at the CLI |
| `query_cube` | **not registered** | registered, denied at the CLI |
| `dry_run` | **not registered** | registered; returns `{"ok": true}`, no rows |

**Verified, not assumed.** `scripts/check_environment.py` performs an MCP
handshake and lists the server's actual tools:

```
[ok] Wren MCP / strict     14 tools, no row-returning tools registered
[ok] Wren MCP / validated  17 tools, row-returning present: ['run_sql', 'query_cube']
```

In `strict` mode the row-returning tools are absent from the protocol. This is
structural, from wrenai's own source (`wren/mcp_server.py`):

```python
def _register_query_tools(mcp, ctx):
    if not ctx.no_connect:
        @mcp.tool() def run_sql(...)
        @mcp.tool() def dry_run(...)
        @mcp.tool() def query_cube(...)
    @mcp.tool() def dry_plan(...)      # outside the gate
```

With `--no-connect`, Wren also opens no database connection at all
(`conn_required=not no_connect` in `wren/serve_cli.py`).

### (3) Wren → PostgreSQL

- **`strict` mode: no connection is ever opened.** Wren cannot read the
  database because it never connects to it.
- **`validated` mode:** Wren connects as `wren_ro`, a role with `SELECT` only,
  and only `dry_run` uses it — which returns `{"ok": true}`, never rows.

One exception, at **setup** time rather than run time: nothing in this project
introspects the database through Wren, because wrenai 0.13.4 has no such
command (`wren context import` supports dbt only). The MDL is authored from
`metadata/schema_description.yaml`. So Wren reads the database at setup time
too: never.

The connection profile at `$WREN_HOME/profiles.yml` holds the **read-only**
credentials, never the owner account — so even a mode change cannot give Wren
write access.

### (4) Python → PostgreSQL

Generated SQL, after passing `benchmark/safety.py`, and the ground-truth SQL.
Both execute as `wren_ro` inside a `READ ONLY` transaction with a statement
timeout.

### (5) PostgreSQL → Python

Result rows. **This is where row data enters the system, and it stops here.**
Rows are compared in `benchmark/evaluator.py` and written to
`results/latest.json`. They are never placed in a prompt, a tool result, or any
message to Claude.

---

## The hole we found, and closed

This section exists because the privacy design failed on first contact, and the
failure was silent.

On the first live run, Wren's MCP server **crashed on startup** — wrenai 0.13.4
declares `mcp>=1.19` but its code uses the v1 API, and pip had installed mcp
2.x, where `FastMCP` was renamed. Claude Code reported **nothing**. It simply
ran with no Wren tools.

Claude then answered the question using **`Bash`**, which was still available.
The answer was correct, so a naive benchmark would have recorded a PASS.

Two failures, both ours:

1. **`--allowedTools` does not restrict anything.** It only *pre-approves*
   tools so they do not prompt. Listing the Wren tools there did not deny Bash.
   Combined with `--permission-mode bypassPermissions`, Claude had the full
   built-in toolset — including a shell that can run `psql`. Rows could have
   reached the model.
2. **A benchmark that cannot detect Wren's absence measures nothing.** The
   report would have claimed "Claude + Wren" while measuring "Claude alone".

Both are now closed:

- **All 18 built-in tools are explicitly denied** (`BLOCKED_BUILTIN_TOOLS` in
  `wren_setup/mcp_config.py`): Bash, BashOutput, KillShell, Read, Write, Edit,
  NotebookEdit, Glob, Grep, WebFetch, WebSearch, Task, Agent, ToolSearch,
  SlashCommand, TodoWrite — plus `run_sql` and `query_cube`.
  `--disallowedTools` is a hard deny, unlike `--allowedTools`.
- **`wren_setup/preflight.py` speaks MCP to the server before any run** and
  refuses to start unless the expected tools are present. In `strict` mode it
  additionally fails if a row-returning tool *is* registered.
- **Every question records `wren_tool_calls`.** If the first question completes
  without touching Wren, the run aborts. The final report lists any question
  answered without Wren.

The general lesson: a deny-by-default posture is only as good as the list of
things denied, and a privacy control you have not observed working is not a
control.

---

## What we do *not* claim

- **We do not claim "no data ever leaves the database".** In `validated` mode
  Wren holds a live connection, and the guarantee there rests on CLI tool
  denial plus PostgreSQL grants — enforcement, not impossibility. Only `strict`
  mode is structural.
- **We do not claim Claude Code cannot be given other tools.** It can; we
  denied them. A future change to `BLOCKED_BUILTIN_TOOLS` would silently
  reopen the hole described above.
- **We have not audited what Anthropic retains.** Prompts and tool results go
  to Anthropic's API through Claude Code. Everything we send is metadata we
  authored plus generated SQL — but it does leave the machine. If your real
  schema descriptions are themselves sensitive, that is the exposure to weigh,
  and this POC does not address it.
- **We have not verified wrenai's full source.** We read `mcp_server.py` and
  `serve_cli.py` closely enough to confirm the `no_connect` gating, and we
  verified the resulting tool list over the wire. We did not audit the rest.
- **Question text is not automatically checked for data values.** N03 names
  "Carol Chen" deliberately. If you add questions containing real identifiers,
  those identifiers reach Claude. Nothing prevents that.

## Residual risks

| Risk | Severity | Mitigation |
|---|---|---|
| `validated` mode's row tools are only denied, not absent | medium | prefer `strict`; preflight asserts the mode |
| Someone edits `BLOCKED_BUILTIN_TOOLS` and reopens Bash | medium | preflight cannot detect this; code review must |
| Schema descriptions are themselves sensitive | project-specific | out of scope for this POC |
| A future wrenai version changes the `no_connect` gate | low | preflight fails loudly if tools appear |
| Question text carries real identifiers | low here (synthetic data) | review new questions |
