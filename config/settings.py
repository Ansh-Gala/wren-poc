"""Configuration loading.

Everything tunable lives in .env; nothing is hard-coded in source. Secrets are
held in fields marked ``repr=False`` so that logging or printing a Settings
object can never leak a password.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]

CONFIG_NAMES = ("A", "B", "C", "D")
PRIVACY_MODES = ("strict", "validated")

# What `claude --effort` accepts, asked of the CLI rather than assumed:
#
#   $ claude --effort bogus -p "hi"
#   Warning: Unknown --effort value 'bogus' -- ignoring it and using the
#   default effort. Valid values: low, medium, high, xhigh, max.
#
# Two call sites used to clamp this to ("medium", "high") independently, so
# CLAUDE_EFFORT_LEVEL=low was accepted, stored, and silently turned back into
# medium. Named once here so a third site cannot disagree with the first two.
EFFORT_LEVELS = ("low", "medium", "high", "xhigh", "max")
DEFAULT_EFFORT_LEVEL = "medium"


def effort_level(value: str | None) -> str:
    """A level the CLI will honour, or the default.

    The CLI ignores an unknown value and warns on stderr, which nothing here
    reads -- so an unrecognised level would fall back to Claude Code's own
    default rather than to this project's, and a run would be neither what
    was asked for nor what the settings say.
    """
    cleaned = (value or "").strip().lower()
    return cleaned if cleaned in EFFORT_LEVELS else DEFAULT_EFFORT_LEVEL


@dataclass(frozen=True)
class Settings:
    pg_host: str
    pg_port: int
    pg_database: str
    pg_user: str
    pg_password: str = field(repr=False, default="")
    pg_readonly_user: str = "wren_ro"
    pg_readonly_password: str = field(repr=False, default="")
    # 100 s and 500 s, as in the Drupal port: a turn can make two model calls
    # (answer, then repair) and two queries.
    statement_timeout_ms: int = 100000

    # Who the benchmark is run as. A real request resolves this from the
    # Drupal session; a suite has no session, so it says so here.
    #
    # Defaulting to 1/'Admin' is deliberate rather than tidy: the question
    # files carry golden SQL asserting assigned_user_id = 1, and every recorded
    # accuracy figure was measured against it. Changing the default would
    # invalidate the comparison rather than improve it.
    benchmark_user_id: int = 1
    benchmark_user_name: str = "Admin"

    # Who the console answers for. It is a tool for one person, so the id
    # comes from .env rather than from a login; the name and departments are
    # read from the database, as Drupal reads them for a session. 0 is
    # nobody: "my tasks" is then answered with a question, never a default id.
    chatbot_user_id: int = 0

    # The "not live" note. A query that reads one of these tables carries the
    # sentence above its table. Drupal sets both on its admin form; these are
    # its install defaults. An empty sentence, or no tables, turns it off.
    freshness_tables: tuple[str, ...] = ("vf_report_task_summary",)
    freshness_message: str = ("This data is not updated in real time. "
                              "Last updated 6 hours ago.")

    # Saved chats: Python's own copies of Drupal's two chat tables, the same
    # columns under the py_ prefix, in the same database. A login of its own,
    # never the read-only one, which must not be able to read them. No user
    # means no saved chats: answers still work, and nothing is written.
    history_db_host: str = "localhost"
    history_db_port: int = 5432
    history_db_name: str = ""
    history_db_user: str = ""
    history_db_password: str = field(repr=False, default="")
    chat_table_prefix: str = "py_"
    # All users together, per calendar month, in effective tokens. 0 is none.
    monthly_token_limit: int = 0

    wren_project_root: Path = ROOT / "wren_projects"
    wren_home: Path = ROOT / "wren_projects" / ".wren_home"
    wren_memory_backend: str = "lancedb"

    claude_command: str = "claude"
    claude_model: str = "sonnet"
    claude_timeout_seconds: int = 500
    # One of EFFORT_LEVELS. Anything else is read as medium: a SELECT does
    # not need extended reasoning, and this is the one setting that silently
    # multiplies the bill.
    #
    # It costs time as well as money, which is why `low` is now reachable.
    # `low` used to be clamped away here, so the value could be set and had
    # no effect. Measured on gpt-5.6-luna, the same lever under its API name
    # `reasoning_effort`, warm mean of five runs on one question:
    #
    #   medium (default)   3.44s to first token, 4.68s total, 75 thinking tokens
    #   low                0.99s to first token, 2.01s total,  9 thinking tokens
    #
    # The model thinks before it emits anything, so the thinking is dead air
    # the caller waits through. Whether `low` costs accuracy is a question for
    # the suite, not for this comment.
    claude_effort_level: str = "medium"
    # The chatbot's own Claude Code config directory. Empty means inherit the
    # operator's, which also inherits their plugins and their hooks.
    claude_config_dir: str = ""

    benchmark_config: str = "D"
    benchmark_privacy_mode: str = "strict"
    debug: bool = False

    llm_provider: str = "cli"   # cli, anthropic, openai, groq or gemini
    cli_lean: bool = False
    # Drupal's stream_answers: off, /ask/stream sends only the final answer.
    stream_answers: bool = True
    # Warm Claude Code processes kept standing by, each serving one question.
    # The CLI costs ~4s to boot and that was being paid on every query; this
    # pays it in advance instead. 0 disables the pool and restores the plain
    # one-shot subprocess, which is also the automatic fallback.
    cli_pool_size: int = 4
    cli_pool_warmup_seconds: float = 3.0
    openai_api_key: str = field(repr=False, default="")
    openai_base_url: str | None = None
    openai_model: str = "gpt-4o"
    # LLM_PROVIDER=anthropic: the Messages API, as Drupal's api_provider
    # "anthropic" reaches it.
    anthropic_api_key: str = field(repr=False, default="")
    anthropic_model: str = "claude-opus-5-5"

    def secrets(self) -> list[str]:
        """Non-empty secret values, for the redacting log formatter."""
        return [s for s in (self.pg_password, self.pg_readonly_password,
                            self.history_db_password, self.openai_api_key,
                            self.anthropic_api_key) if s]

    def project_dir(self, config_name: str) -> Path:
        return self.wren_project_root / f"config_{config_name.upper()}"

    def memory_dir(self, config_name: str) -> Path:
        # Must match wren's own _memory_path(), which derives the location
        # solely from the project directory and ignores WREN_MEMORY_DIR. A
        # path outside the project loads fine but the MCP server never finds
        # it, so recall_queries silently returns no matches.
        return self.project_dir(config_name) / ".wren" / "memory"


def _as_bool(value: str | None, default: bool = False) -> bool:
    if value is None or value == "":
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _as_int(value: str | None, default: int) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default


def _as_float(value: str | None, default: float) -> float:
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return default


def _as_path(value: str | None, default: Path) -> Path:
    if not value:
        return default
    p = Path(value.strip()).expanduser()
    return p if p.is_absolute() else (ROOT / p).resolve()


def load_settings(env_file: str | Path | None = None) -> Settings:
    """Read .env (plus real environment, which wins) into a Settings object."""
    path = Path(env_file) if env_file else ROOT / ".env"
    values: dict[str, str | None] = {}
    if path.exists():
        values.update(dotenv_values(path))
    # A real environment variable overrides the file, so CI and one-off runs
    # can change behaviour without editing .env.
    for key in list(values) + [
        "DATABASE_HOST", "DATABASE_PORT", "DATABASE_NAME", "DATABASE_USER",
        "DATABASE_PASSWORD", "DATABASE_READONLY_USER", "DATABASE_READONLY_PASSWORD",
        "DATABASE_STATEMENT_TIMEOUT_MS", "WREN_PROJECT_ROOT", "WREN_HOME",
        "WREN_MEMORY_BACKEND", "CLAUDE_CLI_COMMAND", "CLAUDE_MODEL",
        "CLAUDE_TIMEOUT_SECONDS", "BENCHMARK_CONFIG", "BENCHMARK_PRIVACY_MODE", "DEBUG",
        "LLM_PROVIDER", "OPENAI_API_KEY", "OPENAI_BASE_URL", "OPENAI_MODEL",
        "CLI_LEAN", "CLAUDE_EFFORT_LEVEL", "CLAUDE_CONFIG_DIR", "CHATBOT_USER_ID",
        "FRESHNESS_TABLES", "FRESHNESS_MESSAGE",
        "HISTORY_DATABASE_HOST", "HISTORY_DATABASE_PORT", "HISTORY_DATABASE_NAME",
        "HISTORY_DATABASE_USER", "HISTORY_DATABASE_PASSWORD", "CHAT_TABLE_PREFIX",
        "MONTHLY_TOKEN_LIMIT", "ANTHROPIC_API_KEY", "ANTHROPIC_MODEL",
        "GROQ_API_KEY", "GEMINI_API_KEY", "CLI_POOL_SIZE", "CLI_POOL_WARMUP_SECONDS",
        "BENCHMARK_USER_ID", "BENCHMARK_USER_NAME", "STREAM_ANSWERS",
    ]:
        if os.environ.get(key):
            values[key] = os.environ[key]

    g = values.get
    provider = (g("LLM_PROVIDER") or "cli").strip().lower()
    project_root = _as_path(g("WREN_PROJECT_ROOT"), ROOT / "wren_projects")

    return Settings(
        pg_host=g("DATABASE_HOST") or "localhost",
        pg_port=_as_int(g("DATABASE_PORT"), 5432),
        pg_database=g("DATABASE_NAME") or "wren_demo",
        pg_user=g("DATABASE_USER") or "postgres",
        pg_password=g("DATABASE_PASSWORD") or "",
        pg_readonly_user=g("DATABASE_READONLY_USER") or "wren_ro",
        pg_readonly_password=g("DATABASE_READONLY_PASSWORD") or "",
        statement_timeout_ms=_as_int(g("DATABASE_STATEMENT_TIMEOUT_MS"), 100000),
        benchmark_user_id=_as_int(g("BENCHMARK_USER_ID"), 1),
        benchmark_user_name=g("BENCHMARK_USER_NAME") or "Admin",
        chatbot_user_id=_as_int(g("CHATBOT_USER_ID"), 0),
        # Present but empty means off, so these fall back only when absent.
        freshness_tables=tuple(
            t.strip() for t in (g("FRESHNESS_TABLES")
                                if g("FRESHNESS_TABLES") is not None
                                else ",".join(Settings.freshness_tables)).split(",")
            if t.strip()),
        freshness_message=(g("FRESHNESS_MESSAGE")
                           if g("FRESHNESS_MESSAGE") is not None
                           else Settings.freshness_message).strip(),
        # The history lives beside the data unless told otherwise; only the
        # login has no fallback, so saved chats are always a decision.
        history_db_host=g("HISTORY_DATABASE_HOST") or g("DATABASE_HOST") or "localhost",
        history_db_port=_as_int(g("HISTORY_DATABASE_PORT") or g("DATABASE_PORT"), 5432),
        history_db_name=g("HISTORY_DATABASE_NAME") or g("DATABASE_NAME") or "",
        history_db_user=(g("HISTORY_DATABASE_USER") or "").strip(),
        history_db_password=g("HISTORY_DATABASE_PASSWORD") or "",
        chat_table_prefix=(g("CHAT_TABLE_PREFIX")
                           if g("CHAT_TABLE_PREFIX") is not None else "py_").strip(),
        monthly_token_limit=max(0, _as_int(g("MONTHLY_TOKEN_LIMIT"), 0)),
        anthropic_api_key=(g("ANTHROPIC_API_KEY") or "").strip(),
        anthropic_model=(g("ANTHROPIC_MODEL") or "claude-opus-5-5").strip(),
        wren_project_root=project_root,
        wren_home=_as_path(g("WREN_HOME"), project_root / ".wren_home"),
        wren_memory_backend=(g("WREN_MEMORY_BACKEND") or "lancedb").strip(),
        claude_command=g("CLAUDE_CLI_COMMAND") or "claude",
        claude_model=(g("CLAUDE_MODEL") or "sonnet").strip(),
        claude_timeout_seconds=_as_int(g("CLAUDE_TIMEOUT_SECONDS"), 500),
        claude_effort_level=(g("CLAUDE_EFFORT_LEVEL") or "medium").strip().lower(),
        claude_config_dir=(g("CLAUDE_CONFIG_DIR") or "").strip(),
        benchmark_config=(g("BENCHMARK_CONFIG") or "D").strip().upper(),
        benchmark_privacy_mode=(g("BENCHMARK_PRIVACY_MODE") or "strict").strip().lower(),
        debug=_as_bool(g("DEBUG"), False),
        llm_provider=provider,
        cli_lean=_as_bool(g("CLI_LEAN"), False),
        stream_answers=_as_bool(g("STREAM_ANSWERS"), True),
        cli_pool_size=_as_int(g("CLI_POOL_SIZE"), 4),
        cli_pool_warmup_seconds=_as_float(g("CLI_POOL_WARMUP_SECONDS"), 3.0),
        # Each branch falls back to "" -- naming a provider whose key is absent
        # is a configuration mistake, and it should be reported as one rather
        # than raising AttributeError from inside the loader, before any code
        # that could say what was wrong has run.
        openai_api_key=(
            (g("GROQ_API_KEY") or "") if provider == "groq"
            else (g("GEMINI_API_KEY") or "") if provider == "gemini"
            else g("OPENAI_API_KEY") or g("GROQ_API_KEY") or g("GEMINI_API_KEY") or ""
        ).strip(),
        openai_base_url=(
            g("OPENAI_BASE_URL") or (
                "https://api.groq.com/openai/v1" if provider == "groq"
                else "https://generativelanguage.googleapis.com/v1beta/openai/" if provider == "gemini"
                else None
            )
        ),
        openai_model=(
            g("OPENAI_MODEL") or (
                "llama-3.3-70b-versatile" if provider == "groq"
                else "gemini-1.5-pro" if provider == "gemini"
                else "gpt-4o"
            )
        ).strip(),
    )
