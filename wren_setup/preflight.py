"""Prove the Wren MCP server actually works before trusting a benchmark run.

This module exists because of a real failure. On the first live run Wren's MCP
server died on startup (an incompatible `mcp` version), Claude Code reported
nothing at all, and Claude answered the question using Bash. The result was
correct, so a naive benchmark would have recorded a PASS and the report would
have claimed to measure "Claude + Wren" while measuring "Claude alone".

A benchmark that cannot tell "Wren helped" from "Wren was absent" measures
nothing. So before any run, we spawn the server ourselves, speak MCP to it, and
require the expected tools to be present.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

from config.settings import Settings
from wren_setup.mcp_config import DISALLOWED_TOOLS, build_mcp_config

# Tools that must be present, or the semantic layer is not really in play.
REQUIRED_TOOLS = {
    "get_mdl",
    "list_models",
    "describe_model",
    "get_instructions",
    "recall_queries",
    "dry_plan",
}


class PreflightError(RuntimeError):
    """The Wren MCP server is not usable."""


def list_mcp_tools(config_name: str, privacy_mode: str, settings: Settings) -> list[str]:
    """Start the server over stdio, complete the handshake, return tool names."""
    server = build_mcp_config(config_name, privacy_mode, settings)["mcpServers"]["wren"]
    env = {**os.environ, **server["env"]}

    proc = subprocess.Popen(
        [server["command"], *server["args"]],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        bufsize=1,
    )

    def send(payload: dict) -> None:
        assert proc.stdin is not None
        proc.stdin.write(json.dumps(payload) + "\n")
        proc.stdin.flush()

    def read_reply(want_id: int, limit: int = 80) -> dict | None:
        assert proc.stdout is not None
        for _ in range(limit):
            line = proc.stdout.readline()
            if not line:
                return None
            line = line.strip()
            if not line.startswith("{"):
                continue  # the banner and log lines are not protocol
            try:
                message = json.loads(line)
            except json.JSONDecodeError:
                continue
            if message.get("id") == want_id:
                return message
        return None

    try:
        send({
            "jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "wren-poc-preflight", "version": "1"},
            },
        })
        if read_reply(1) is None:
            stderr = (proc.stderr.read() if proc.stderr else "")[-1500:]
            raise PreflightError(
                "Wren MCP server did not complete the MCP handshake.\n"
                f"stderr:\n{stderr.strip() or '(empty)'}"
            )

        send({"jsonrpc": "2.0", "method": "notifications/initialized"})
        send({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        reply = read_reply(2)
        if reply is None or "result" not in reply:
            stderr = (proc.stderr.read() if proc.stderr else "")[-1500:]
            raise PreflightError(
                "Wren MCP server did not return a tool list.\n"
                f"stderr:\n{stderr.strip() or '(empty)'}"
            )
        return sorted(t["name"] for t in reply["result"].get("tools", []))
    except OSError as exc:
        raise PreflightError(f"could not launch the Wren MCP server: {exc}") from exc
    finally:
        proc.kill()
        proc.wait(timeout=10)


def check(config_name: str, privacy_mode: str, settings: Settings) -> list[str]:
    """Raise PreflightError unless the server exposes a usable tool set."""
    project = settings.project_dir(config_name)
    if not (project / "target" / "mdl.json").exists():
        raise PreflightError(
            f"configuration {config_name} has not been built "
            f"({project / 'target' / 'mdl.json'} is missing). "
            "Run: python scripts/build_wren.py"
        )

    profiles = settings.wren_home / "profiles.yml"
    if not profiles.exists():
        raise PreflightError(
            f"no Wren connection profile at {profiles}. Wren needs one even in "
            "strict mode, to know the SQL dialect. Run: python scripts/build_wren.py"
        )

    tools = list_mcp_tools(config_name, privacy_mode, settings)
    if not tools:
        raise PreflightError("Wren MCP server exposed no tools at all.")

    missing = REQUIRED_TOOLS - set(tools)
    if missing:
        raise PreflightError(
            f"Wren MCP server is missing expected tools: {sorted(missing)}\n"
            f"It exposed: {tools}"
        )

    # In strict mode the row-returning tools must not even exist.
    if privacy_mode == "strict":
        leaked = [t for t in ("run_sql", "query_cube", "dry_run") if t in tools]
        if leaked:
            raise PreflightError(
                f"strict mode should not register {leaked}, but the server did. "
                "--no-connect may not have taken effect."
            )

    return tools


def assert_wren_was_used(tools_used: list[str]) -> None:
    """Raise if a completed question never touched the semantic layer."""
    if not any(t.startswith("mcp__wren__") for t in tools_used):
        raise PreflightError(
            "Claude answered without calling a single Wren MCP tool "
            f"(tools used: {tools_used or 'none'}). The run would measure "
            "Claude alone, not Claude + Wren."
        )


def wren_tool_calls(tools_used: list[str]) -> int:
    return sum(1 for t in tools_used if t.startswith("mcp__wren__"))


def summarize_tools(tools: list[str]) -> str:
    row_tools = [t for t in ("run_sql", "query_cube") if t in tools]
    note = f"  row-returning tools present: {row_tools}" if row_tools else \
           "  no row-returning tools registered"
    return f"  {len(tools)} tools: {', '.join(tools)}\n{note}"


def blocked_tools_note() -> str:
    return f"denied: {', '.join(DISALLOWED_TOOLS)} + all Claude built-ins"


def wren_home_profiles_path(settings: Settings) -> Path:
    return settings.wren_home / "profiles.yml"
