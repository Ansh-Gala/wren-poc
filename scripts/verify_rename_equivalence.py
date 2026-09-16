"""Prove a renamed query returns what the original returned.

Values are compared positionally and headings are ignored: the whole point of
the migration is that the headings change. Row order is normalised by sorting,
because neither query carries an ORDER BY unless its author wrote one, and
Postgres is free to differ. Values are stringified before comparison so that a
column whose type is unchanged but whose driver representation differs (a
Decimal read through a renamed alias) does not read as a difference. SQL NULL
is held distinct from any string a column could contain -- a bare `str(v)`
would collapse NULL and the literal text 'None' onto the same sentinel, which
would read as agreement when the two queries genuinely disagree.

Nothing here raises on SQL error. A failing query is a finding to report, in
the same spirit as run_readonly.
"""

from __future__ import annotations

from config.settings import load_settings
from database.connection import connect


def _rows(cur, sql: str) -> list[tuple[str, ...]]:
    cur.execute(sql)
    return sorted(
        tuple("\x00NULL" if v is None else str(v) for v in row)
        for row in cur.fetchall()
    )


def verify_pairs(pairs: list[tuple[str, str]]) -> list[str]:
    settings = load_settings()
    failures: list[str] = []
    with connect(settings, readonly=True) as conn:
        for old_sql, new_sql in pairs:
            cur = conn.cursor()
            try:
                old = _rows(cur, old_sql)
            except Exception as exc:
                conn.rollback()
                failures.append(f"old query failed: {exc}\n  {old_sql}")
                continue
            try:
                new = _rows(cur, new_sql)
            except Exception as exc:
                conn.rollback()
                failures.append(f"new query failed: {exc}\n  {new_sql}")
                continue
            if len(old) != len(new):
                failures.append(
                    f"row count {len(old)} -> {len(new)}\n  {old_sql}")
                continue
            for i, (a, b) in enumerate(zip(old, new)):
                if a != b:
                    failures.append(f"row {i} {a!r} != {b!r}\n  {old_sql}")
                    break
    return failures
