"""Thin subprocess wrapper around the `wren` CLI."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from config.settings import Settings


class WrenError(RuntimeError):
    """A `wren` command exited non-zero."""


def wren_executable() -> str:
    bindir = Path(sys.executable).parent
    for name in ("wren.exe", "wren"):
        candidate = bindir / name
        if candidate.exists():
            return str(candidate)
    return "wren"


def wren_env(settings: Settings, project_dir: Path | None = None, **extra: str) -> dict:
    """Environment for a `wren` subprocess.

    PYTHONUTF8 is mandatory on Windows: wrenai 0.13.4 writes UTF-8 templates
    without an explicit encoding, which raises UnicodeEncodeError under the
    cp1252 default. See docs/wren-findings.md.
    """
    env = dict(os.environ)
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    env["WREN_HOME"] = str(settings.wren_home)
    if project_dir is not None:
        env["WREN_PROJECT_HOME"] = str(project_dir)
    env.update(extra)
    return env


def run_wren(
    args: list[str],
    settings: Settings,
    project_dir: Path | None = None,
    timeout: int = 300,
    check: bool = True,
    **extra_env: str,
) -> subprocess.CompletedProcess:
    proc = subprocess.run(
        [wren_executable(), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        env=wren_env(settings, project_dir, **extra_env),
    )
    if check and proc.returncode != 0:
        raise WrenError(
            f"`wren {' '.join(args)}` exited {proc.returncode}\n"
            f"stdout: {proc.stdout.strip()[:2000]}\n"
            f"stderr: {proc.stderr.strip()[:2000]}"
        )
    return proc


def wren_version(settings: Settings) -> str | None:
    try:
        proc = run_wren(["--version"], settings, timeout=60, check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    return proc.stdout.strip() or None
