"""The record behind a row (for TMS, the initiative) and its colour.

`columns` is stripped when debug is off -- it holds raw database column names
-- so the frontend receives headings and rows and no way to tell which column
is the record's id, or which colour each row carries. So the position is
named here, on the server, where the real column names are still in hand.
What a click on the record opens is pipeline.links' job.

The colour is a second lookup because it is usually not projected. A question
about initiatives selects the columns the question asked about; the colour bar
is a thing the grid draws whether or not anyone asked for it. When the answer
already carries the colour, that value is used and nothing is queried.

Both outputs are deliberately shaped to survive redaction: integer positions
and CSS class codes. Neither names a column, a table or any SQL.
"""

from __future__ import annotations

import re

# Which columns, codes and lookup table is the product.yaml entity with a
# `colour`, and `colours` (name -> {code, hex}); with none, every position is
# None and nothing is looked up.
#
# The TMS codes are not derivable from the frontend. All four of its colour
# maps run class -> name, and both e_wh and nocolor render as "White", so
# inverting them is ambiguous. They were resolved from the data instead, by
# joining tms_initiative_flat to tms_task_flat on the initiative id and
# reading the two spellings off the same row.

# A table or column name from product.yaml is interpolated: run_readonly
# binds nothing, so only a plain identifier is accepted.
_PLAIN_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _record() -> dict:
    from pipeline.metadata import profile

    return profile().colour_record() or {}


def colour_class(value) -> str | None:
    """A stored colour as the CSS class the app's renderers expect.

    Both spellings are accepted because both are stored: the initiative table
    holds the name ("Black") and the task table holds the class ("a_bl"). An
    unknown value returns None rather than a guess -- the bar is then simply
    not drawn, which is honest, where a wrong class would state a priority the
    data does not.
    """
    from pipeline.metadata import profile

    if value is None:
        return None
    class_by_name = {str(name).lower(): str(colour["code"])
                     for name, colour in profile().colours().items()
                     if isinstance(colour, dict) and "code" in colour}
    text = str(value).strip()
    if text.lower() in class_by_name.values():
        return text.lower()
    return class_by_name.get(text.lower())


def indices(columns: list[str] | None) -> dict:
    """Where the initiative's id, reference and colour sit in a result.

    Positions rather than names, for the reason the whole presentation layer
    uses positions: a result may project one name twice, and the frontend keys
    its rows by index. The first occurrence wins, which is the one a join
    projects from its leading table.
    """
    names = [str(c) for c in (columns or [])]

    def first(candidates) -> int | None:
        for i, name in enumerate(names):
            if name in candidates:
                return i
        return None

    record = _record()
    return {"id": first(record.get("id_columns") or ()),
            "ref_id": first(record.get("ref_columns") or ()),
            "colour": first(record.get("colour_columns") or ())}


def colours_from_result(result: dict, where: dict) -> dict:
    """The colour of each row's initiative, taken from the answer itself.

    Used when the query already projected the colour, which costs nothing.
    """
    id_at, colour_at = where.get("id"), where.get("colour")
    if id_at is None or colour_at is None:
        return {}
    out = {}
    for row in (result.get("rows") or []):
        if id_at >= len(row) or colour_at >= len(row):
            continue
        css = colour_class(row[colour_at])
        if css is not None and row[id_at] is not None:
            out[str(row[id_at])] = css
    return out


def _ids_on_the_page(result: dict, id_at: int) -> list[int]:
    """The initiative ids in the rows shown, as integers.

    Integers rather than strings, and coerced here rather than trusted: the
    values are interpolated into the lookup below because
    database.connection.run_readonly takes a statement and no parameters. An
    id that is not an integer is dropped, so nothing but a number can reach
    the SQL.
    """
    seen: dict[int, None] = {}
    for row in (result.get("rows") or []):
        if id_at >= len(row) or row[id_at] is None:
            continue
        try:
            seen[int(row[id_at])] = None
        except (TypeError, ValueError):
            continue
    return list(seen)


def colours_by_lookup(result: dict, where: dict, settings) -> dict:
    """The colour of each row's initiative, read from the initiative table.

    One statement, bounded by the primary key and by the page already
    returned, and skipped entirely when there is no initiative id to look up.
    A failure returns nothing: the colour bar is decoration on an answer that
    is already correct, and an answer must not be lost to it.
    """
    id_at = where.get("id")
    if id_at is None:
        return {}
    record = _record()
    table, id_column, colour_column = record.get("table"), record.get("id"), record.get("colour")
    if not all(isinstance(n, str) and _PLAIN_NAME.match(n) for n in (table, id_column, colour_column)):
        return {}
    ids = _ids_on_the_page(result, id_at)
    if not ids:
        return {}

    from database.connection import run_readonly

    sql = (f"SELECT {id_column}, {colour_column} "
           f"FROM {table} "
           f"WHERE {id_column} IN ({', '.join(str(i) for i in ids)})")
    query = run_readonly(settings, sql, getattr(settings, "statement_timeout_ms", None))
    if query.error:
        return {}

    out = {}
    for record_id, colour in query.rows:
        css = colour_class(colour)
        if css is not None:
            out[str(record_id)] = css
    return out


def with_row_colour(result, columns: list[str] | None, settings=None):
    """A result with each row's colour attached, as `row_colour`.

    `at` is the position of the record's id, and `colours` maps each id to
    its CSS class code; omitted when no row has a colour. Additive, like every
    other presentation field: `columns` and `rows` keep exactly what
    PostgreSQL said. Anything that is not a result passes through -- a
    clarification has no rows.

    `columns` is passed in rather than read off the result because this has to
    run against the real column names, and the caller is the last place that
    still holds them.
    """
    if not isinstance(result, dict):
        return result

    where = indices(columns)
    if where["id"] is None:
        return result

    found = colours_from_result(result, where)
    if not found and settings is not None:
        found = colours_by_lookup(result, where, settings)
    if not found:
        return result
    return {**result, "row_colour": {"at": where["id"], "colours": found}}
