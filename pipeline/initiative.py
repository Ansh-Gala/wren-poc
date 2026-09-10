"""The initiative behind a row: which columns identify it, and its colour.

Two things the grid needs and cannot work out for itself.

`columns` is stripped when debug is off -- it holds raw database column names
-- so the frontend receives headings and rows and no way to tell which column
is the initiative's id. It therefore cannot know which cell to make clickable,
or which id to hand the details dialog. So the positions are named here, on
the server, where the real column names are still in hand.

The colour is a second lookup because it is usually not projected. A question
about initiatives selects the columns the question asked about; the colour bar
is a thing the grid draws whether or not anyone asked for it. When the answer
already carries the colour, that value is used and nothing is queried.

Both outputs are deliberately shaped to survive redaction: integer positions
and CSS class codes. Neither names a column, a table or any SQL.
"""

from __future__ import annotations

# The colour as tms_business_object_flat stores it, mapped to the CSS class
# the app's own renderers already use.
#
# This mapping is not derivable from the frontend. All four of its colour maps
# run class -> name, and both e_wh and nocolor render as "White", so inverting
# them is ambiguous. It was resolved from the data instead, by joining
# tms_business_object_flat to tms_task_flat on the initiative id and reading
# the two spellings off the same row: Black/a_bl on 196 initiatives,
# Green/d_gr on 95, White/e_wh on 9, Red/b_re on 1. Yellow is listed for
# completeness -- no row carries it today, and a colour that appeared later
# would otherwise render as nothing at all.
_CLASS_BY_NAME = {
    "black": "a_bl",
    "red": "b_re",
    "yellow": "c_ye",
    "green": "d_gr",
    "white": "e_wh",
}

_CLASSES = frozenset(_CLASS_BY_NAME.values())

# The columns that identify an initiative, in each of the two spellings the
# two flat tables use. bo_id is tms_task_flat's name for business_object_id.
_ID_COLUMNS = ("business_object_id", "bo_id")
_REF_COLUMNS = ("business_object_ref_id",)
_COLOUR_COLUMNS = ("business_object_color",)


def colour_class(value) -> str | None:
    """A stored colour as the CSS class the app's renderers expect.

    Both spellings are accepted because both are stored: the initiative table
    holds the name ("Black") and the task table holds the class ("a_bl"). An
    unknown value returns None rather than a guess -- the bar is then simply
    not drawn, which is honest, where a wrong class would state a priority the
    data does not.
    """
    if value is None:
        return None
    text = str(value).strip()
    if text.lower() in _CLASSES:
        return text.lower()
    return _CLASS_BY_NAME.get(text.lower())


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

    return {"id": first(_ID_COLUMNS),
            "ref_id": first(_REF_COLUMNS),
            "colour": first(_COLOUR_COLUMNS)}


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
    ids = _ids_on_the_page(result, id_at)
    if not ids:
        return {}

    from database.connection import run_readonly

    sql = ("SELECT business_object_id, business_object_color "
           "FROM tms_business_object_flat "
           f"WHERE business_object_id IN ({', '.join(str(i) for i in ids)})")
    query = run_readonly(settings, sql, getattr(settings, "statement_timeout_ms", None))
    if query.error:
        return {}

    out = {}
    for bo_id, colour in query.rows:
        css = colour_class(colour)
        if css is not None:
            out[str(bo_id)] = css
    return out


def with_initiative(result, columns: list[str] | None, settings=None):
    """A result with the initiative positions and the row colours attached.

    Additive, like every other presentation field: `columns` and `rows` keep
    exactly what PostgreSQL said. Anything that is not a result passes through
    -- a clarification has no rows, and an aggregate has no initiative to open.

    `columns` is passed in rather than read off the result because this has to
    run against the real column names, and the caller is the last place that
    still holds them.
    """
    if not isinstance(result, dict):
        return result

    where = indices(columns)
    out = {**result, "initiative": where}

    if where["id"] is None:
        return out

    found = colours_from_result(result, where)
    if not found and settings is not None:
        found = colours_by_lookup(result, where, settings)
    if found:
        out["colours"] = found
    return out
