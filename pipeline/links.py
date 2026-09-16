"""Where a row can be followed: the issue it is, and the file it holds.

The same problem `initiative.py` solves, for the two views added on
16 September 2026. `columns` is stripped from a response when debug is off --
it holds raw database column names -- so the frontend receives headings and
rows and no way to tell which cell opens an issue or a file. The positions are
named here, on the server, where the real column names are still in hand.

Two positions per target rather than one, because the cell a person clicks is
not the cell holding the value:

  * an issue is opened by its id, but the readable cell is its title, and a
    grid of primary keys is not something anyone wants to read;
  * a file is opened by its uri, but the readable cell is its name, and the
    uri is hidden by the column hierarchy.

So each target carries `at` -- the cell to make clickable -- and the position
of the value to follow. When only the value column is projected, `at` falls
back to it: a result that shows the id and nothing else should still open.

Everything here is integer positions. Nothing names a column, a table or any
SQL, so it survives redaction the way the initiative block does.
"""

from __future__ import annotations

# The issue's own identifier. Only one spelling: the view was given this
# column on 16 September 2026 precisely so a row could be followed.
_ISSUE_ID_COLUMNS = ("issue_id",)
# What a person reads instead of the id.
_ISSUE_LABEL_COLUMNS = ("issue_title",)

# The stored file and the name it is shown under.
_FILE_URI_COLUMNS = ("file_uri",)
_FILE_LABEL_COLUMNS = ("file_name",)


def _first(names: list[str], candidates) -> int | None:
    for i, name in enumerate(names):
        if name in candidates:
            return i
    return None


def indices(columns: list[str] | None) -> dict:
    """Where an issue and a file sit in a result, by position.

    The first occurrence of each wins, matching `initiative.indices`: a result
    may project one name twice, and the frontend keys its rows by index.
    """
    names = [str(c) for c in (columns or [])]

    issue_id = _first(names, _ISSUE_ID_COLUMNS)
    issue_label = _first(names, _ISSUE_LABEL_COLUMNS)
    file_uri = _first(names, _FILE_URI_COLUMNS)
    file_label = _first(names, _FILE_LABEL_COLUMNS)

    return {
        "issue": {
            "id_at": issue_id,
            # Click the title where there is one, otherwise the id itself.
            "at": issue_label if issue_label is not None else issue_id,
        } if issue_id is not None else None,
        "file": {
            "uri_at": file_uri,
            "at": file_label if file_label is not None else file_uri,
        } if file_uri is not None else None,
    }


def with_links(result, columns: list[str] | None):
    """A result with the followable positions attached.

    Additive, like every other presentation field: `columns` and `rows` keep
    exactly what PostgreSQL said. Anything that is not a result passes through
    -- a clarification has no rows, and a count has nothing to follow.

    `columns` is passed in rather than read off the result because this has to
    run against the real column names, and the caller is the last place that
    still holds them.
    """
    if not isinstance(result, dict):
        return result

    where = indices(columns)
    if where["issue"] is None and where["file"] is None:
        # Nothing to follow. Say so by omission rather than by a block of
        # nulls the frontend would have to pick apart.
        return result
    return {**result, "links": where}
