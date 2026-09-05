"""Create the demo database, seed it, and report what was built.

    python scripts/setup_demo.py

Wren project configurations are built separately by scripts/build_wren.py so
that a database problem and a Wren problem never present as the same failure.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from config.logging import get_logger, register_secrets  # noqa: E402
from config.settings import load_settings  # noqa: E402
from database.setup import setup_all  # noqa: E402


def main() -> int:
    settings = load_settings()
    register_secrets(settings.secrets())
    log = get_logger("setup_demo", settings.debug)

    if not settings.pg_password:
        log.error(
            "DATABASE_PASSWORD is empty. Copy .env.example to .env and set the "
            "PostgreSQL owner password before running setup."
        )
        return 1

    try:
        counts = setup_all(settings)
    except RuntimeError as exc:
        log.error("%s", exc)
        return 1

    print("\nDemo database ready:")
    for table, n in counts.items():
        print(f"  {table:<12} {n:>4} rows")
    print(f"\n  database        {settings.pg_database}")
    print(f"  read-only role  {settings.pg_readonly_user}")
    print("\nNext: python scripts/build_wren.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
