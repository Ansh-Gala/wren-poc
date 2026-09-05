"""Shared fixtures.

Integration tests need a live PostgreSQL with the demo database already set up
(``python scripts/setup_demo.py``). They are marked ``integration`` and skipped
automatically when the database is unreachable, so ``pytest`` is always runnable.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config.settings import Settings, load_settings  # noqa: E402


def pytest_configure(config):
    config.addinivalue_line(
        "markers", "integration: needs live PostgreSQL, Wren or Claude CLI"
    )


@pytest.fixture(scope="session")
def settings() -> Settings:
    s = load_settings()
    if not s.pg_password and not s.pg_readonly_password:
        pytest.skip("no database credentials in .env")
    from database.connection import run_readonly

    probe = run_readonly(s, "SELECT 1", 3000)
    if probe.error:
        pytest.skip(f"demo database unreachable: {probe.error}")
    return s


@pytest.fixture
def tmp_settings(tmp_path) -> Settings:
    """Settings pointing at a throwaway project root, for pure-unit tests."""
    return Settings(
        pg_host="localhost",
        pg_port=5432,
        pg_database="wren_demo",
        pg_user="postgres",
        pg_password="unit-test-password",
        pg_readonly_password="unit-test-ro-password",
        wren_project_root=tmp_path / "wren_projects",
        wren_home=tmp_path / "wren_projects" / ".wren_home",
    )
