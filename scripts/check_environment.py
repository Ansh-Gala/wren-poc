"""Check every prerequisite and report actionable failures.

    python scripts/check_environment.py

Never prints a password or a token.
"""

from __future__ import annotations

import sys

import _bootstrap  # noqa: F401

from benchmark.questions import load_questions
from llm_api.cli_provider import claude_version, detect_claude
from config.settings import CONFIG_NAMES, load_settings
from database.connection import run_readonly
from wren_setup.helpers import wren_version
from wren_setup.mcp_config import all_disallowed_tools
from wren_setup.preflight import PreflightError, check as preflight_check

OK, BAD, WARN = "  ok  ", " FAIL ", " warn "
problems: list[str] = []


def report(status: str, label: str, detail: str = "", fix: str = "") -> None:
    print(f"[{status}] {label}" + (f"  -  {detail}" if detail else ""))
    if status == BAD:
        problems.append(f"{label}: {fix or detail}")


def main() -> int:
    settings = load_settings()
    print("Wren + Claude POC environment check\n")

    # ---- Python ----------------------------------------------------------
    v = sys.version_info
    if (v.major, v.minor) >= (3, 11):
        report(OK, "Python", f"{v.major}.{v.minor}.{v.micro}")
    else:
        report(BAD, "Python", f"{v.major}.{v.minor}", "wrenai requires Python 3.11+")

    # ---- config ----------------------------------------------------------
    if settings.pg_password:
        report(OK, "DATABASE_PASSWORD", "set")
    else:
        report(BAD, "DATABASE_PASSWORD", "empty",
               "copy .env.example to .env and set the PostgreSQL password")
    if settings.pg_readonly_password:
        report(OK, "DATABASE_READONLY_PASSWORD", "set")
    else:
        report(BAD, "DATABASE_READONLY_PASSWORD", "empty",
               "set it in .env, then re-run scripts/setup_demo.py")

    # ---- PostgreSQL ------------------------------------------------------
    probe = run_readonly(settings, "SELECT 1", 5000)
    if probe.error:
        report(BAD, "PostgreSQL", probe.error.splitlines()[0][:120],
               "check DATABASE_* in .env and that the server is running")
    else:
        report(OK, "PostgreSQL",
               f"{settings.pg_host}:{settings.pg_port}/{settings.pg_database} "
               f"as {settings.pg_readonly_user}")

        counts = {}
        for table in ("users", "workflows", "tasks"):
            r = run_readonly(settings, f"SELECT count(*) FROM {table}", 5000)
            counts[table] = None if r.error else r.rows[0][0]
        if counts == {"users": 15, "workflows": 8, "tasks": 50}:
            report(OK, "demo data", "15 users, 8 workflows, 50 tasks")
        else:
            report(BAD, "demo data", str(counts), "run: python scripts/setup_demo.py")

        write = run_readonly(settings, "INSERT INTO users(id, full_name) VALUES (999,'x')", 5000)
        if write.error:
            report(OK, "read-only role", "writes correctly refused")
        else:
            report(BAD, "read-only role", "a write SUCCEEDED",
                   "the benchmark role has write access; re-run setup_demo.py")

    # ---- Wren ------------------------------------------------------------
    wv = wren_version(settings)
    if wv:
        report(OK, "wren CLI", wv)
    else:
        report(BAD, "wren CLI", "not found",
               "pip install 'wrenai[postgres,mcp,memory]' 'mcp<2'")

    try:
        import mcp  # noqa: F401
        from mcp.server.fastmcp import FastMCP  # noqa: F401
        from importlib.metadata import version as _pkgver
        report(OK, "mcp package", f"{_pkgver('mcp')} (v1 API present)")
    except Exception:
        from importlib.metadata import version as _pkgver
        try:
            found = _pkgver("mcp")
        except Exception:
            found = "missing"
        report(BAD, "mcp package", f"{found} - FastMCP unavailable",
               "pip install 'mcp<2'  (wrenai 0.13.4 needs the v1 API; "
               "with mcp 2.x the Wren MCP server dies on import and Claude "
               "silently runs with no Wren tools)")

    profiles = settings.wren_home / "profiles.yml"
    if profiles.exists():
        report(OK, "wren connection profile", str(profiles))
    else:
        report(BAD, "wren connection profile", "missing",
               "run: python scripts/build_wren.py")

    for name in CONFIG_NAMES:
        mdl = settings.project_dir(name) / "target" / "mdl.json"
        if mdl.exists():
            report(OK, f"config {name}", "built")
        else:
            report(BAD, f"config {name}", "not built",
                   "run: python scripts/build_wren.py")

    memory = settings.memory_dir("D")
    if memory.exists() and any(memory.iterdir()):
        report(OK, "config D query memory", f"{settings.wren_memory_backend} at {memory.name}")
    else:
        report(WARN, "config D query memory", "empty",
               "run: python scripts/build_wren.py --only D")

    # ---- Claude ----------------------------------------------------------
    exe = detect_claude(settings.claude_command)
    cv = claude_version(settings.claude_command)
    if exe and cv:
        report(OK, "Claude Code CLI", cv)
    elif exe:
        report(BAD, "Claude Code CLI", "found but `claude --version` failed", str(exe))
    else:
        report(BAD, "Claude Code CLI", f"'{settings.claude_command}' not on PATH",
               "install from https://claude.com/claude-code")

    # Authentication: report only whether it looks configured. Never a token.
    if exe:
        from pathlib import Path
        creds = [Path.home() / ".claude" / ".credentials.json",
                 Path.home() / ".claude.json"]
        if any(p.exists() for p in creds):
            report(OK, "Claude authentication", "local credentials present (not read)")
        else:
            report(WARN, "Claude authentication", "could not be confirmed",
                   "run `claude` once interactively to sign in")

    # ---- MCP handshake ---------------------------------------------------
    for mode in ("strict", "validated"):
        try:
            tools = preflight_check("D", mode, settings)
            rows = [t for t in ("run_sql", "query_cube") if t in tools]
            detail = f"{len(tools)} tools" + (
                f", row-returning present: {rows} (denied at the CLI)" if rows
                else ", no row-returning tools registered")
            report(OK, f"Wren MCP / {mode}", detail)
        except PreflightError as exc:
            report(BAD, f"Wren MCP / {mode}", str(exc).splitlines()[0][:140],
                   "see docs/wren-findings.md")
        except Exception as exc:
            report(BAD, f"Wren MCP / {mode}", f"{type(exc).__name__}: {exc}"[:140])

    # ---- questions -------------------------------------------------------
    try:
        questions = load_questions()
        categories = sorted({q.category for q in questions})
        report(OK, "benchmark questions",
               f"{len(questions)} across {len(categories)} categories "
               f"({''.join(categories)})")
    except Exception as exc:
        report(BAD, "benchmark questions", str(exc)[:120])

    print(f"\nTool policy: {', '.join(all_disallowed_tools()[:4])}, ... "
          f"({len(all_disallowed_tools())} tools denied)")

    if problems:
        print(f"\n{len(problems)} problem(s) to fix:\n")
        for p in problems:
            print(f"  - {p}")
        return 1

    print("\nEnvironment is ready.")
    print("  python scripts/verify_ground_truth.py")
    print("  python scripts/run_single.py R06")
    print("  python scripts/run_benchmark.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
