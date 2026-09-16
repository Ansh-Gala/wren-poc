"""Drive the local Claude Code CLI as a subprocess.

No Anthropic SDK, no API key, no HTTP. Authentication is entirely the local
Claude Code installation's business, and nothing here reads or forwards a
credential.

`--output-format stream-json` is used rather than plain `json` because the
event stream names every MCP tool Claude actually called. That is what makes
"which Wren tools were used" answerable in run_single.py, and it lets the
failure classifier tell a Wren MCP error apart from a Claude error.
"""

from __future__ import annotations

import time
import json
import os
import shutil
import subprocess
import threading
from pipeline.models import ClaudeRun, Session
from claude.prompts import build_system_prompt, build_user_prompt
from config.settings import Settings
from llm_api.provider import LLMProvider


def detect_claude(command: str = "claude") -> str | None:
    """Resolve the Claude Code executable, or None if it is not installed."""
    return shutil.which(command)


def claude_version(command: str = "claude") -> str | None:
    exe = detect_claude(command)
    if not exe:
        return None
    try:
        out = subprocess.run(
            [exe, "--version"], capture_output=True, text=True, timeout=30
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout.strip() or None


def build_command(
    question: str,
    mcp_config_path: Path,
    privacy_mode: str,
    settings: Settings,
    session: Session | None = None,
) -> list[str]:
    if settings.cli_lean:
        # No MCP, no built-in tools, default system prompt replaced. One turn.
        from claude.prompts import build_lean_system_prompt
        cmd = [
            settings.claude_command,
            "-p",
            build_user_prompt(question, session,
                              context=session.context_block if session else None,
                              lean=True),
            "--output-format",
            "stream-json",
            "--verbose",
            "--system-prompt",
            build_lean_system_prompt(),
            "--tools",
            "",
            "--permission-mode",
            "bypassPermissions",
        ]
        if settings.claude_model:
            cmd += ["--model", settings.claude_model]
        return cmd

    # Imported here rather than at module scope: a lean-only deployment ships
    # no wren_setup, and this is the only branch that needs it.
    from wren_setup.mcp_config import all_disallowed_tools, allowed_tools

    cmd = [
        settings.claude_command,
        "-p",
        build_user_prompt(question, session,
                          context=session.context_block if session else None),
        "--output-format",
        "stream-json",
        "--verbose",
        "--mcp-config",
        str(mcp_config_path),
        # Only the Wren server from the file above. Any MCP server the user has
        # configured globally is excluded, so runs are reproducible.
        "--strict-mcp-config",
        "--append-system-prompt",
        build_system_prompt(),
        # bypassPermissions so no run can stall waiting for a prompt that
        # nobody is there to answer. Safety comes from --disallowedTools below,
        # which is a hard deny, plus a SELECT-only database role. Note that
        # --allowedTools alone does NOT restrict anything: it only pre-approves.
        # The deny list is what actually keeps Bash away from the database.
        "--permission-mode",
        "bypassPermissions",
    ]

    # Allow only Wren's read-only tools...
    cmd += ["--allowedTools", *allowed_tools(privacy_mode)]
    # ...and deny the row-returning Wren tools plus every Claude built-in, so
    # the only way to answer is through the semantic layer.
    cmd += ["--disallowedTools", *all_disallowed_tools()]

    if settings.claude_model:
        cmd += ["--model", settings.claude_model]

    return cmd


def apply_result_event(run: ClaudeRun, event: dict) -> None:
    """Read the CLI's terminating `result` event onto a run.

    Shared with llm_api.cli_pool, which reads the same event off a live pipe
    rather than a finished process's stdout. One implementation because the
    usage accounting below is the kind of thing that drifts silently if it is
    written twice.
    """
    run.result_text = event.get("result") or ""
    run.duration_ms = float(event.get("duration_ms") or 0.0)
    run.cost_usd = event.get("total_cost_usd")
    run.session_id = event.get("session_id")
    run.num_turns = event.get("num_turns")
    # The CLI reports usage the way Anthropic bills it: fresh input, cache
    # writes and cache reads are separate counters. Summing all three gives
    # the prompt size the model actually saw, which is the number comparable
    # to the API provider's prompt_tokens.
    usage = event.get("usage") or {}
    run.prompt_tokens = (
        int(usage.get("input_tokens") or 0)
        + int(usage.get("cache_creation_input_tokens") or 0)
        + int(usage.get("cache_read_input_tokens") or 0)
    )
    run.completion_tokens = int(usage.get("output_tokens") or 0)
    run.cache_read_tokens = int(usage.get("cache_read_input_tokens") or 0)
    run.cache_write_tokens = int(usage.get("cache_creation_input_tokens") or 0)
    run.ok = not event.get("is_error", False)
    if event.get("is_error"):
        run.error = event.get("subtype") or "claude reported an error"


def parse_stream_json(stdout: str) -> ClaudeRun:
    """Read the stream-json event log.

    Tolerates non-JSON noise on stdout: a warning line must not lose us an
    otherwise good run.
    """
    tools: list[str] = []
    mcp_errors: list[str] = []
    run = ClaudeRun(ok=False)

    for line in stdout.splitlines():
        line = line.strip()
        if not line or not line.startswith("{"):
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue

        etype = event.get("type")

        if etype == "assistant":
            for block in event.get("message", {}).get("content", []) or []:
                if isinstance(block, dict) and block.get("type") == "tool_use":
                    name = block.get("name")
                    if name:
                        tools.append(name)

        elif etype == "user":
            # Tool results come back as user-role events; an is_error result
            # from a wren tool is a Wren failure, not a Claude failure.
            for block in event.get("message", {}).get("content", []) or []:
                if not isinstance(block, dict) or block.get("type") != "tool_result":
                    continue
                if block.get("is_error"):
                    content = block.get("content")
                    text = content if isinstance(content, str) else json.dumps(content)
                    mcp_errors.append(text[:500])

        elif etype == "result":
            apply_result_event(run, event)

    run.tools_used = tools
    run.mcp_errors = mcp_errors
    return run


# One pool per (command, model, system prompt). Module-level because the
# whole point is to outlive a single request: get_provider() builds a new
# CLILocalProvider every turn, so anything held on the instance would be
# thrown away before it finished warming.
_POOLS: dict[tuple, "ClaudePool"] = {}
_POOLS_LOCK = threading.Lock()


def _pool_for(settings: Settings, system_prompt: str) -> "ClaudePool | None":
    """The warm pool for this configuration, or None when pooling is off.

    Keyed on the system prompt as well as the command and model: a pooled
    process is booted with `--system-prompt` already applied, so a process
    warmed for one prompt cannot answer under another.
    """
    if settings.cli_pool_size <= 0:
        return None
    from llm_api.cli_pool import ClaudePool

    key = (settings.claude_command, settings.claude_model, hash(system_prompt))
    with _POOLS_LOCK:
        pool = _POOLS.get(key)
        if pool is None:
            pool = ClaudePool(
                command=settings.claude_command,
                system_prompt=system_prompt,
                model=settings.claude_model or None,
                size=settings.cli_pool_size,
                warmup=settings.cli_pool_warmup_seconds,
                reply_timeout=min(90.0, float(settings.claude_timeout_seconds)),
            )
            _POOLS[key] = pool
        return pool


def shutdown_pools() -> None:
    """Kill every warm process. For a clean exit, and for tests."""
    with _POOLS_LOCK:
        pools = list(_POOLS.values())
        _POOLS.clear()
    for pool in pools:
        pool.close()


class CLILocalProvider(LLMProvider):
    def ask(
        self,
        question: str,
        mcp_config_path: Path,
        privacy_mode: str,
        settings: Settings,
        session: Session | None = None,
    ) -> ClaudeRun:
        # A warm process, when there is one. The lean path only: the MCP
        # branch passes --mcp-config and a different tool set, and warming
        # those has not been measured.
        if settings.cli_lean:
            from claude.prompts import build_lean_system_prompt
            pool = _pool_for(settings, build_lean_system_prompt())
            if pool is not None:
                user_prompt = build_user_prompt(
                    question, session,
                    context=session.context_block if session else None,
                    lean=True)
                run = pool.ask(user_prompt)
                if run is not None:
                    return run
                # Fell through: no warm process, or one died mid-answer. The
                # one-shot path below is slower but always available, and an
                # answer matters more than the four seconds.

        exe = detect_claude(settings.claude_command)
        if not exe:
            return ClaudeRun(
                ok=False,
                error=(
                    f"Claude Code CLI not found (looked for {settings.claude_command!r} "
                    "on PATH). Install it from https://claude.com/claude-code, then "
                    "run `claude --version` to confirm."
                ),
            )

        cmd = build_command(question, mcp_config_path, privacy_mode, settings, session)

        # Inherit the environment so Claude Code finds its own credentials, but do
        # not add any secret of ours to it.
        env = os.environ.copy()
        env.pop("ANTHROPIC_API_KEY", None)  # force local Claude Code auth

        started = time.perf_counter()
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=settings.claude_timeout_seconds,
                env=env,
            )
        except subprocess.TimeoutExpired:
            waited = (time.perf_counter() - started) * 1000
            return ClaudeRun(
                ok=False,
                timed_out=True,
                duration_ms=waited,
                wall_ms=waited,
                error=f"claude timed out after {settings.claude_timeout_seconds}s",
            )
        except OSError as exc:
            return ClaudeRun(ok=False, error=f"failed to launch claude: {exc}")

        elapsed_ms = (time.perf_counter() - started) * 1000
        run = parse_stream_json(proc.stdout)
        run.exit_code = proc.returncode
        run.stderr = (proc.stderr or "")[-4000:]

        # Both numbers, always. `duration_ms` is the CLI's own account of the
        # query and excludes its startup; `wall_ms` is what the caller waited.
        # Keeping only the first is how ~4.5s of process boot per query stayed
        # invisible -- it was measured here and then discarded.
        run.wall_ms = elapsed_ms
        if not run.duration_ms:
            run.duration_ms = elapsed_ms

        if proc.returncode != 0:
            run.ok = False
            if not run.error:
                run.error = (
                    f"claude exited {proc.returncode}: {run.stderr.strip()[:300]}"
                )
        elif not run.result_text and not run.error:
            run.ok = False
            run.error = "claude produced no result event"

        return run
