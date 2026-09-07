# SQL chatbot

Ask a question in English, get an answer from PostgreSQL. A local Claude Code
CLI writes the SQL, a read-only role runs it, and a small web console shows
both the answer and what the system understood.

This is the production branch: the application and nothing else. The
benchmark, the question sets, the evaluation harness, the semantic-registry
sources, the Wren/MCP integration and the project documentation all live on
`develop`. Work there and promote; a change committed here is lost at the next
promotion.

## What it does

One HTTP endpoint and one page. A question arrives, and before any SQL is
written the system repairs obvious typos against the schema's own vocabulary,
decides whether the question starts a new topic or continues the last one, and
assembles only the context that decision calls for.

The model is given the schema, the business rules and a set of worked
examples, and is asked for SQL. What comes back is parsed, checked against the
schema, and rejected outright if it is anything other than a read. Only then
is it executed.

Rows never reach the model -- only metadata does: the schema descriptions,
the business rules and the worked examples under `metadata/`. Generated SQL is
parsed and rejected unless it is a single read, and it executes as a role that
holds SELECT and nothing else.

If the question cannot be answered as asked, the system says so instead of
guessing -- and if it asks you something back, your reply is understood as an
answer to that question rather than as a new topic.

## Requirements

- Python 3.11+
- PostgreSQL, reachable, with the `tms_*` views this project queries
- [Claude Code CLI](https://claude.com/claude-code) on `PATH`

Confirm the last one with `claude --version`. The server refuses to start
without it, because every figure this project has ever reported was produced
through it.

## Install

```
python -m venv .venv
.venv\Scripts\activate                 # Windows
# source .venv/bin/activate            # macOS/Linux
pip install -r requirements.txt
```

## Configure

```
copy .env.example .env                 # cp on macOS/Linux
```

Then set, at a minimum:

| Variable | Value |
|---|---|
| `DATABASE_HOST`, `DATABASE_PORT`, `DATABASE_NAME` | where PostgreSQL is |
| `DATABASE_READONLY_USER`, `DATABASE_READONLY_PASSWORD` | the role queries run as |
| `LLM_PROVIDER` | `cli` |
| `CLI_LEAN` | `true` |

Both values are required, not defaults. This branch ships only the lean
path: `LLM_PROVIDER` anything but `cli`, or `CLI_LEAN=false`, and the server
exits at startup saying so. The MCP path it would otherwise select needs
`wren_setup`, which is not part of a deployment.

The query role should hold `SELECT` and nothing more. `pipeline/safety.py`
rejects writes before they are sent, but a read-only grant is what makes that
belt-and-braces rather than the only line of defence.

## Run

```
python scripts/serve_api.py
```

Then open <http://localhost:8000/>. The console is served from the same
process, so there is no CORS to configure and no second thing to start.

```
python scripts/serve_api.py --port 9000
python scripts/serve_api.py --context-mode none     # no conversation memory
python scripts/serve_api.py --log ''                # stop recording turns
```

By default every turn is appended as JSONL under `logs/console/raw/`, which
is gitignored. Questions people actually type are the best source of cases
nobody thought to write; `--log ''` turns that off.

## Endpoint

`POST /ask` with `{"question": "...", "session_id": "..."}` returns the
decision, the SQL, the rows, the conversation state and the token counts. The
full response contract is documented at the top of
[ui/api.js](ui/api.js) -- that file is the only one that talks to the backend,
so it is also the only one to read when integrating something else.

`GET /health` returns `{"ok": true}` and the live session count.

## Tests

```
python -m pytest
```

Tests needing a live database or the Claude CLI are marked `integration`;
`python -m pytest -m "not integration"` skips them.

## Layout

```
pipeline/     Answering a question: repair, classify, prompt, parse,
              validate, execute, evaluate, decide what to offer next
claude/       Prompt construction and response parsing
config/       Settings and logging
database/     Read-only connection handling
llm_api/      Provider abstraction over the Claude CLI
metadata/     Schema descriptions, business rules, worked examples,
              entity vocabulary -- what the model is told
ui/           The console: one page, no build step, no dependencies
scripts/      serve_api.py, and the bootstrap it imports
tests/        The tests for the above
```

Everything here is reachable from `scripts/serve_api.py`. Nothing is kept
for reference.

`metadata/` is generated on `develop` from the semantic registry and promoted
here as output. Change it there, not on this branch.

## Architecture, privacy and the follow-up layer

Documented on `develop`, under `docs/`: `architecture.md`, `privacy.md` (what
crosses each boundary, connection by connection), `followup-layer.md` (repair,
clarification and suggestions) and `branching.md` (this workflow).
