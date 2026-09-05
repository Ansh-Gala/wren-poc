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


@dataclass(frozen=True)
class Settings:
    pg_host: str
    pg_port: int
    pg_database: str
    pg_user: str
    pg_password: str = field(repr=False, default="")
    pg_readonly_user: str = "wren_ro"
    pg_readonly_password: str = field(repr=False, default="")
    statement_timeout_ms: int = 15000

    wren_project_root: Path = ROOT / "wren_projects"
    wren_home: Path = ROOT / "wren_projects" / ".wren_home"
    wren_memory_backend: str = "lancedb"

    claude_command: str = "claude"
    claude_model: str = ""
    claude_timeout_seconds: int = 180

    benchmark_config: str = "D"
    benchmark_privacy_mode: str = "strict"
    debug: bool = False
    
    llm_provider: str = "cli" # 'cli' or 'openai'
    openai_api_key: str = field(repr=False, default="")
    openai_base_url: str | None = None
    openai_model: str = "gpt-4o"

    def secrets(self) -> list[str]:
        """Non-empty secret values, for the redacting log formatter."""
        return [s for s in (self.pg_password, self.pg_readonly_password) if s]

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
    ]:
        if os.environ.get(key):
            values[key] = os.environ[key]

    g = values.get
    project_root = _as_path(g("WREN_PROJECT_ROOT"), ROOT / "wren_projects")

    return Settings(
        pg_host=g("DATABASE_HOST") or "localhost",
        pg_port=_as_int(g("DATABASE_PORT"), 5432),
        pg_database=g("DATABASE_NAME") or "wren_demo",
        pg_user=g("DATABASE_USER") or "postgres",
        pg_password=g("DATABASE_PASSWORD") or "",
        pg_readonly_user=g("DATABASE_READONLY_USER") or "wren_ro",
        pg_readonly_password=g("DATABASE_READONLY_PASSWORD") or "",
        statement_timeout_ms=_as_int(g("DATABASE_STATEMENT_TIMEOUT_MS"), 15000),
        wren_project_root=project_root,
        wren_home=_as_path(g("WREN_HOME"), project_root / ".wren_home"),
        wren_memory_backend=(g("WREN_MEMORY_BACKEND") or "lancedb").strip(),
        claude_command=g("CLAUDE_CLI_COMMAND") or "claude",
        claude_model=(g("CLAUDE_MODEL") or "").strip(),
        claude_timeout_seconds=_as_int(g("CLAUDE_TIMEOUT_SECONDS"), 180),
        benchmark_config=(g("BENCHMARK_CONFIG") or "D").strip().upper(),
        benchmark_privacy_mode=(g("BENCHMARK_PRIVACY_MODE") or "strict").strip().lower(),
        debug=_as_bool(g("DEBUG"), False),
        llm_provider=(g("LLM_PROVIDER") or "cli").strip().lower(),
        openai_api_key=(
            g("GROQ_API_KEY") if (g("LLM_PROVIDER") or "").strip().lower() == "groq"
            else g("GEMINI_API_KEY") if (g("LLM_PROVIDER") or "").strip().lower() == "gemini"
            else g("OPENAI_API_KEY") or g("GROQ_API_KEY") or g("GEMINI_API_KEY") or ""
        ).strip(),
        openai_base_url=(
            g("OPENAI_BASE_URL") or (
                "https://api.groq.com/openai/v1" if (g("LLM_PROVIDER") or "").strip().lower() == "groq"
                else "https://generativelanguage.googleapis.com/v1beta/openai/" if (g("LLM_PROVIDER") or "").strip().lower() == "gemini"
                else None
            )
        ),
        openai_model=(
            g("OPENAI_MODEL") or (
                "llama-3.3-70b-versatile" if (g("LLM_PROVIDER") or "").strip().lower() == "groq"
                else "gemini-1.5-pro" if (g("LLM_PROVIDER") or "").strip().lower() == "gemini"
                else "gpt-4o"
            )
        ).strip(),
    )
