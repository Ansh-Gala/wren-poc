"""Generate the --mcp-config file Claude Code uses to launch Wren's MCP server.

Two privacy modes, both of which keep database rows away from Claude:

``strict``     `wren serve mcp --no-connect`. run_sql, query_cube and dry_run
               are never registered and Wren opens no database connection at
               all. Structural, enforced by wrenai's own code.

``validated``  Wren connects as the read-only PostgreSQL role so that dry_run
               is available for validation. run_sql and query_cube exist but
               are denied by Claude Code via --disallowedTools, and the role
               has no write grants.

Verified against wren/mcp_server.py and wren/serve_cli.py in wrenai 0.13.4.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from config.settings import Settings

# Tools Claude must never call, for two distinct reasons.
#
# PRIVACY -- these return database rows. Denied in every mode, belt and braces
# with --no-connect. Named exactly as Claude Code addresses MCP tools:
# mcp__<server>__<tool>, where <server> is the key in mcpServers below.
ROW_RETURNING_TOOLS = [
    "mcp__wren__run_sql",
    "mcp__wren__query_cube",
]

# TOKEN COST -- these return correct but enormous payloads that would dominate
# the context window. Measured against config D, 3 tables / 24 columns:
#   list_functions   19638 tokens   (the whole SQL function reference)
#   get_mdl           2893 tokens   (the entire compiled MDL)
#   describe_schema   1632 tokens   (superseded by per-model describe_model)
# describe_model returns the same information one table at a time, which is
# what makes the cost scale with the question rather than with the schema.
OVERSIZED_TOOLS = [
    "mcp__wren__list_functions",
    "mcp__wren__get_mdl",
    "mcp__wren__describe_schema",
    # get_context advertises semantic retrieval, but on this project it always
    # answers with strategy "full" -- the entire schema description, 1639
    # tokens, plus ~4s of latency. describe_model returns the same information
    # one table at a time. Measured, not assumed: see the probe in
    # docs/wren-findings.md.
    "mcp__wren__get_context",
]

DISALLOWED_TOOLS = [*ROW_RETURNING_TOOLS, *OVERSIZED_TOOLS]

# Claude Code's own built-in tools, all explicitly denied.
#
# This is not paranoia. In the first live run Wren's MCP server failed to start,
# Claude Code reported nothing, and Claude quietly answered the question using
# Bash instead -- which means it could have run psql and pulled real rows back
# into the conversation. Denying run_sql while leaving Bash open defeats the
# entire privacy requirement, and the benchmark would have measured "Claude
# alone" while reporting "Claude + Wren".
BLOCKED_BUILTIN_TOOLS = [
    "Bash", "BashOutput", "KillShell",
    "Read", "Write", "Edit", "NotebookEdit",
    "Glob", "Grep",
    "WebFetch", "WebSearch",
    "Task", "Agent", "ToolSearch", "SlashCommand", "TodoWrite",
]


def all_disallowed_tools() -> list[str]:
    """Everything Claude must not touch: row-returning Wren tools + built-ins."""
    return [*DISALLOWED_TOOLS, *BLOCKED_BUILTIN_TOOLS]

# Tools Claude may call. None of these return database rows, so allowing them
# does not weaken the privacy guarantee -- in strict mode Wren holds no
# database connection at all.
#
# The schema and business rules used to be inlined into the system prompt
# (21712 characters on every call, whether or not the question needed them).
# They are served on demand instead: cost now scales with what a question
# actually touches rather than with the size of the database.
_BASE_TOOLS = [
    # Schema, on demand.
    "mcp__wren__list_models",       #  272 tokens -- names only
    "mcp__wren__describe_model",    # ~760 tokens per table
    # Business rules and terminology, on demand.
    "mcp__wren__get_instructions",  # ~1545 tokens, only when a question needs it
    "mcp__wren__list_knowledge",
    # Confirmed NL->SQL exemplars.
    "mcp__wren__recall_queries",
    "mcp__wren__list_stored_queries",
    # Validation.
    "mcp__wren__dry_plan",
]

def allowed_tools(privacy_mode: str) -> list[str]:
    """Tools Claude may call. dry_run only exists when Wren is connected."""
    tools = list(_BASE_TOOLS)
    if privacy_mode == "validated":
        # Returns {"ok": true} only -- validates SQL without returning rows.
        tools.append("mcp__wren__dry_run")
    return tools


# Claude Code addresses an MCP tool as mcp__<server>__<tool>; the MCP protocol
# itself uses the bare name. Both spellings are needed: the bare one to call
# the server, the prefixed one so tool usage is recorded identically no matter
# which provider ran the question.
MCP_PREFIX = "mcp__wren__"


def to_mcp_name(name: str) -> str:
    """mcp__wren__dry_plan -> dry_plan (what the MCP server answers to)."""
    return name[len(MCP_PREFIX):] if name.startswith(MCP_PREFIX) else name


def to_claude_name(name: str) -> str:
    """dry_plan -> mcp__wren__dry_plan (how results record a Wren call)."""
    return name if name.startswith(MCP_PREFIX) else MCP_PREFIX + name


def wren_executable() -> str:
    """Path to the `wren` console script inside the active interpreter's env."""
    bindir = Path(sys.executable).parent
    for name in ("wren.exe", "wren"):
        candidate = bindir / name
        if candidate.exists():
            return str(candidate)
    return "wren"


def build_mcp_config(config_name: str, privacy_mode: str, settings: Settings) -> dict:
    if privacy_mode not in ("strict", "validated"):
        raise ValueError(f"unknown privacy mode: {privacy_mode!r}")

    # --project is passed explicitly as well as via WREN_PROJECT_HOME: it is
    # what `wren serve mcp` itself recommends, and it removes any doubt about
    # which knowledge configuration the server loaded.
    args = [
        "serve", "mcp",
        "--transport", "stdio",
        "--project", str(settings.project_dir(config_name)),
        "--quiet",
    ]
    if privacy_mode == "strict":
        args.append("--no-connect")

    env = {
        # Selects which knowledge configuration (A/B/C/D) this server serves.
        "WREN_PROJECT_HOME": str(settings.project_dir(config_name)),
        "WREN_MEMORY_DIR": str(settings.memory_dir(config_name)),
        # grep, not lancedb. recall_queries on the lancedb backend loads
        # sentence-transformers inside the stdio server and never returns
        # (measured: still running after 45s, while grep answers in 0.0s).
        # The grep backend reads knowledge/sql/*.md, which wrenai documents as
        # the source of truth anyway; LanceDB is only ever a derived index.
        "WREN_MEMORY_BACKEND": "grep",
        "WREN_HOME": str(settings.wren_home),
        # wrenai 0.13.4 writes UTF-8 text without an explicit encoding in
        # several places, which raises UnicodeEncodeError under the Windows
        # cp1252 default. See docs/wren-findings.md.
        "PYTHONUTF8": "1",
        "PYTHONIOENCODING": "utf-8",
    }

    if privacy_mode == "validated":
        # Wren connects with the SELECT-only role, never the owner account.
        env["WREN_DB_STATEMENT_TIMEOUT"] = str(settings.statement_timeout_ms)

    return {
        "mcpServers": {
            "wren": {
                "command": wren_executable(),
                "args": args,
                "env": env,
            }
        }
    }


def write_mcp_config(config_name: str, privacy_mode: str, settings: Settings) -> Path:
    config = build_mcp_config(config_name, privacy_mode, settings)
    out_dir = settings.wren_project_root / "mcp"
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"mcp.{config_name.upper()}.{privacy_mode}.json"
    path.write_text(json.dumps(config, indent=2), encoding="utf-8")
    return path


def connection_env(settings: Settings) -> dict[str, str]:
    """Environment for a *connected* Wren, using the read-only role only."""
    return {
        **os.environ,
        "PYTHONUTF8": "1",
        "PYTHONIOENCODING": "utf-8",
        "WREN_HOME": str(settings.wren_home),
    }
