# Data flow for one question

A trace of exactly what happens, with the real commands and a real observed
run. Everything below was captured from a live execution, not written from the
design.

## 0. Preflight (once per run)

`wren_setup/preflight.py` spawns the MCP server, completes the MCP handshake,
and lists the tools. The run aborts unless `get_mdl`, `list_models`,
`describe_model`, `get_instructions`, `recall_queries` and `dry_plan` are all
present. In `strict` mode it also fails if `run_sql`, `query_cube` or `dry_run`
*are* present.

```
[ok] Wren MCP / strict     14 tools, no row-returning tools registered
[ok] Wren MCP / validated  17 tools, row-returning present: ['run_sql', 'query_cube']
```

## 1. Python builds the MCP config

`wren_setup/mcp_config.py` writes `wren_projects/mcp/mcp.D.strict.json`:

```json
{
  "mcpServers": {
    "wren": {
      "command": ".../.venv/Scripts/wren.exe",
      "args": ["serve", "mcp", "--transport", "stdio",
               "--project", ".../wren_projects/config_D",
               "--quiet", "--no-connect"],
      "env": {
        "WREN_PROJECT_HOME": ".../wren_projects/config_D",
        "WREN_MEMORY_DIR":   ".../wren_projects/memory_D",
        "WREN_MEMORY_BACKEND": "lancedb",
        "WREN_HOME":         ".../wren_projects/.wren_home",
        "PYTHONUTF8": "1",
        "PYTHONIOENCODING": "utf-8"
      }
    }
  }
}
```

`PYTHONUTF8=1` is required, not cosmetic: wrenai 0.13.4 writes UTF-8 text
without an explicit encoding in several places and crashes under the Windows
cp1252 default.

## 2. Python invokes Claude Code

```bash
claude -p "Question: <the question>

Consult Wren, then reply with only the JSON object containing the SQL
that answers this question." \
  --output-format stream-json --verbose \
  --mcp-config wren_projects/mcp/mcp.D.strict.json \
  --strict-mcp-config \
  --append-system-prompt "<claude/prompts.py SYSTEM_PROMPT>" \
  --permission-mode bypassPermissions \
  --allowedTools mcp__wren__get_mdl mcp__wren__list_models \
                 mcp__wren__describe_model mcp__wren__describe_schema \
                 mcp__wren__get_data_source mcp__wren__list_functions \
                 mcp__wren__get_instructions mcp__wren__recall_queries \
                 mcp__wren__get_context mcp__wren__list_stored_queries \
                 mcp__wren__list_knowledge mcp__wren__dry_plan \
  --disallowedTools mcp__wren__run_sql mcp__wren__query_cube \
                    Bash BashOutput KillShell Read Write Edit NotebookEdit \
                    Glob Grep WebFetch WebSearch Task Agent ToolSearch \
                    SlashCommand TodoWrite \
  --model sonnet
```

Three things to note:

- **`--strict-mcp-config`** means no MCP server configured elsewhere on the
  machine can leak into the run.
- **`--allowedTools` does not restrict.** It only pre-approves. The
  `--disallowedTools` list is what actually keeps Bash away from the database.
  We learned this the hard way — see `docs/privacy.md`.
- **`ANTHROPIC_API_KEY` is removed** from the child environment, forcing local
  Claude Code auth.

## 3. Claude consults Wren over MCP

An observed sequence for *"Who owns workflows but is not doing any of the task
work themselves?"* (question R06):

| # | Tool | What came back |
|---|---|---|
| 1 | `mcp__wren__describe_schema` | 3 models, 22 columns, 3 relationships, with descriptions |
| 2 | `mcp__wren__get_instructions` | 23 business rules from `knowledge/rules/` |
| 3 | `mcp__wren__recall_queries` | nearest confirmed NL→SQL exemplars |
| 4 | `mcp__wren__dry_plan` | the SQL expanded to PostgreSQL dialect |

**Metadata only. No row ever crossed this boundary.**

## 4. Claude returns SQL

```json
{"sql": "SELECT DISTINCT u.full_name FROM users u JOIN workflows w ON w.owner_user_id = u.id WHERE NOT EXISTS (SELECT 1 FROM tasks t WHERE t.assigned_user_id = u.id) ORDER BY u.full_name"}
```

## 5. Python parses it

`claude/parser.py` tries five strategies in order — whole-reply JSON, last
```sql fence, last generic fence, embedded JSON, bare statement — and records
which one matched, so parser fragility is itself measurable. Here: `json`.

## 6. Python gates it

`benchmark/safety.py` parses the statement with sqlglot and rejects anything
that is not a single read-only query, backed by a keyword screen that ignores
string literals and comments (so a task named `'Update browser matrix'` does
not trip it).

## 7. Python executes it

As `wren_ro`, inside `SET TRANSACTION READ ONLY` with a statement timeout.
Immediately afterwards, the ground-truth query runs the same way — in the same
moment, because seed dates are relative to `CURRENT_DATE`.

## 8. Python compares

`benchmark/evaluator.py`:

- NULL stays distinct from `''` and `0`; `Decimal`/`int`/`float` compare with
  tolerance; dates normalise to ISO.
- Column order and aliases are ignored (a permutation is searched for).
- Row order is enforced only when the question asked for one.
- A second, column-tolerant metric records whether the right *rows* were
  selected even if extra columns came back.

Result for R06: 1 row, `Noah Novak` — **PASS**.

## 9. Python classifies any failure

`benchmark/classify.py`, deterministic signals first (timeout, CLI failure,
Wren tool error, parser miss, safety rejection, PostgreSQL SQLSTATE), then a
sqlglot AST diff as a heuristic. Anything not confidently identified is
`RESULT_MISMATCH` rather than a guess.

## 10. Python writes the record

Appended to `results/raw/<config>.<privacy>.jsonl` immediately, so a long run is
watchable and resumable. Final reports go to `results/latest.{json,csv,md}`.

**Rows reached Python and stopped there.** Nothing in step 7 or 8 re-entered a
prompt, a tool result, or any message to Claude.

## Observed cost and latency (Sonnet 5, warm cache)

| | Per question |
|---|---|
| Turns | 3–6 |
| Wall clock | 16–25 s |
| Tokens touched | 90k–187k (≈91% cache reads) |
| Cost | ≈ $0.13 |

The token figure looks large but the *unique* context is only ~28k — Claude
Code's system prompt, 14 tool definitions, and Wren's returned metadata. It is
re-sent on every turn as Claude calls Wren again, which is what prompt caching
absorbs.
