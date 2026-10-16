"""What a reader of these rows is told about data that is not live.

Ported from the Drupal port's ChatRuntime::freshnessNote and
SqlText::namesTable. Some tables are snapshots -- the weekly report table is
rebuilt a few times a day -- and a person reading its rows should not take them
for the state of things this minute. A query that reads one carries a fixed
sentence, shown above its table.

Drupal sets the tables and the sentence on its admin form; here they are
FRESHNESS_TABLES and FRESHNESS_MESSAGE in .env.
"""

from __future__ import annotations

import sqlglot
from sqlglot import exp


def freshness_note(settings, queries: list[str | None]) -> str | None:
    """The sentence, or None when no query reads a listed table or the
    sentence is empty."""
    note = (settings.freshness_message or "").strip()
    if not note:
        return None
    for table in settings.freshness_tables:
        for sql in queries:
            if names_table(sql, table):
                return note
    return None


def names_table(sql: str | None, name: str | None) -> bool:
    """Whether a statement reads a table, outside comments and string literals.

    ``name`` is "table" or "schema.table", quoted or not, in any case. A bare
    name matches the table in any schema. A qualified one matches that schema
    and an unqualified reference, which the search path may resolve to it,
    but not another schema's table of the same name.

    Drupal scans identifiers because it has no parser; sqlglot lists the
    tables, which is the same answer on every case its check holds.
    """
    parts = [part.strip(' \t"').lower() for part in str(name or "").split(".")]
    table = parts.pop()
    schema = parts.pop() if parts else None
    if not table or not sql:
        return False
    try:
        tree = sqlglot.parse_one(str(sql), read="postgres")
    except Exception:
        return False
    if tree is None:
        return False
    for found in tree.find_all(exp.Table):
        if found.name.lower() != table:
            continue
        qualifier = (found.db or "").lower()
        if schema is None or not qualifier or qualifier == schema:
            return True
    return False
