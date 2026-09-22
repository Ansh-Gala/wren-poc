"""Display order and hidden columns, resolved against a result's own columns.

Presentation only, and positional. The order comes from
metadata/column_hierarchy.yaml, which lists columns by name; a result carries
columns by position and may carry one name twice, so the answer is a list of
positions rather than a list of names. Anything else would push that
resolution onto the caller, which is where it would go wrong.

A column the file does not mention is not an error -- generated aliases such
as `avg_delay_days` have never appeared in any registry -- so unlisted columns
keep their own relative order and follow everything named.

Nothing here reaches the model. That is what makes it safe: the built system
prompt is compared byte for byte against the PHP port, and a file that changed
the prompt would have to move in lockstep with it.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml

META_DIR = Path(__file__).resolve().parents[1] / "metadata"


@lru_cache(maxsize=1)
def _config() -> dict:
    """The parsed configuration, or an empty one.

    A missing file is not an error: presentation is an enhancement, and a
    deployment without the file should show columns in the order the query
    projected them rather than fail to answer.
    """
    path = META_DIR / "column_hierarchy.yaml"
    if not path.is_file():
        return {}
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _spec(tables: list[str] | None) -> dict:
    """The first configured table among those the query touched.

    First rather than merged: a join's columns come from two tables and
    merging their priority lists would invent an order neither file states.
    active_tables is in FROM order, so the leading table is the subject.
    """
    configured = _config().get("tables") or {}
    for table in tables or []:
        if table in configured:
            return configured[table] or {}
    return {}


# The aggregations ag-grid ships. An unknown name is not an error to ag-grid:
# it yields blank aggregates, which is the same silent failure an unknown
# column name has in this file -- so it is rejected here instead.
_AGG_FUNCS = frozenset({"sum", "first", "last", "min", "max", "count", "avg"})


EMPTY_GROUPING = {"row_groups": [], "pivot_columns": [], "value_columns": []}


def grouping(columns: list[str] | None, tables: list[str] | None,
             wanted: bool = False) -> dict:
    """Which columns to group by, and which to aggregate, as positions.

    Positions for the same reason as `order`: a result may project one name
    twice and the grid keys its rows by index.

    Two conditions, and both have to hold. `wanted` is the model's answer to
    whether THIS answer reads better grouped; the file below says which
    columns may head a group and which are totals. The file alone was not
    enough: it fires on every answer off a nominated table, which is how an
    answer nobody asked to have grouped came back grouped anyway. The model
    alone is not enough either -- it would have to name columns, and naming
    columns is the thing this module exists to keep it away from.

    Empty lists when either says no, which is the normal case. Grouping
    changes what a row means -- a page of groups is not a page of records --
    so it is never turned on because a column happened to be present.

    `pivot_columns` is read but stays empty until a table nominates one:
    pivot is the half that breaks the layout, and the frontend suppresses it
    while nothing is nominated.
    """
    if not wanted:
        return dict(EMPTY_GROUPING)

    names = list(columns or [])
    if not names:
        return dict(EMPTY_GROUPING)

    spec = _spec(tables)

    def positions(wanted: list[str]) -> list[int]:
        return [i for i, name in enumerate(names) if name in set(wanted or [])]

    values = []
    for entry in (spec.get("value_columns") or []):
        if not isinstance(entry, dict):
            continue
        agg = str(entry.get("aggFunc") or "").strip().lower()
        if agg not in _AGG_FUNCS:
            # Named but unusable. Dropped rather than passed through, because
            # ag-grid would render an empty column and say nothing.
            continue
        for i, name in enumerate(names):
            if name == entry.get("column"):
                values.append({"index": i, "aggFunc": agg})

    return {
        "row_groups": positions(spec.get("row_groups")),
        "pivot_columns": positions(spec.get("pivot_columns")),
        "value_columns": values,
    }


def presentation(columns: list[str] | None, tables: list[str] | None) -> dict:
    """Where each column should sit, and which start collapsed.

    Returns positions into ``columns``. ``order`` is always a permutation of
    every position, so the frontend can trust that reordering loses nothing.
    """
    names = list(columns or [])
    if not names:
        return {"order": [], "hidden": []}

    spec = _spec(tables)
    priority = list(spec.get("priority") or [])
    # Not named hidden_names: that is a module-level function now, and the
    # local would shadow it.
    hidden_set = set(spec.get("hidden") or [])

    rank = {name: i for i, name in enumerate(priority)}
    # A stable sort on (rank, original position) puts the named columns in the
    # file's order and leaves everything else in the order the query projected
    # it -- the only order that result has.
    order = sorted(
        range(len(names)),
        key=lambda i: (rank.get(names[i], len(priority)), i),
    )
    hidden = [i for i, name in enumerate(names) if name in hidden_set]
    return {"order": order, "hidden": hidden}


def hidden_names(tables: list[str] | None) -> frozenset[str]:
    """The columns the hierarchy says are not worth showing for these tables.

    Exposed because "not worth showing" and "not worth grouping or sorting by"
    are the same judgement, and the follow-up layer needs the second one.
    task_display_status is the case that proves it: the schema says "for UI
    display only. Do not filter or group by this column; use task_status", and
    it is hidden here for that reason -- so one declaration can settle both
    rather than the two layers keeping separate lists that drift.
    """
    return frozenset(_spec(tables).get("hidden") or [])
