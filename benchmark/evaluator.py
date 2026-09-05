"""Result-based correctness.

Generated SQL is never compared to expected SQL as text: two very different
queries can be equally correct. What is compared is what the database returned.

Two normalisations make that comparison fair without making it loose:

* **Column order and aliasing are ignored.** `SELECT name, cnt` and
  `SELECT cnt AS total, who` are the same answer. A permutation of the actual
  columns is searched for one that matches. This is the standard execution-
  accuracy approach used by Spider and friends.
* **Row order is ignored unless the question asked for an order.** Questions
  carry `ordered: true` when they say "newest first", "top 3", "alphabetically".

Type normalisation is deliberately narrow. NULL stays distinct from '' and 0,
and duplicate rows remain significant, because collapsing either would hide
real errors.
"""

from __future__ import annotations

from collections import Counter
from datetime import date, datetime
from decimal import Decimal
from itertools import permutations
from typing import Any

from benchmark.models import QueryResult

# Beyond this, permutation search is skipped and columns compare positionally.
# 8! = 40320 is still cheap; 9! would not be, and no benchmark question needs it.
MAX_PERMUTATION_COLUMNS = 8

# Numeric equality tolerance, expressed as decimal places. AVG returns Decimal
# and COUNT returns int; both must compare equal to a plain float.
_FLOAT_PRECISION = 9


class _Null:
    """Sentinel so NULL never compares equal to '' or 0."""

    __slots__ = ()

    def __repr__(self) -> str:
        return "NULL"

    def __hash__(self) -> int:
        return hash("\x00__NULL__")

    def __eq__(self, other: object) -> bool:
        return isinstance(other, _Null)


NULL = _Null()

# Unique tag so a normalised boolean cannot compare equal to a number.
# Returning the bare bool is not enough: in Python True == 1 == 1.0 and the
# three hash identically, so a boolean column would silently match an integer
# one inside a Counter.
_BOOL_TAG = object()


def normalize_value(value: Any) -> Any:
    if value is None:
        return NULL
    # bool before int: bool is a subclass of int.
    if isinstance(value, bool):
        return (_BOOL_TAG, value)
    if isinstance(value, (int, float, Decimal)):
        try:
            return round(float(value), _FLOAT_PRECISION)
        except (ValueError, OverflowError):
            return str(value)
    if isinstance(value, datetime):
        # Midnight timestamps and plain dates describe the same day.
        if value.hour == value.minute == value.second == value.microsecond == 0:
            return value.date().isoformat()
        return value.isoformat(sep=" ")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (list, tuple)):
        return tuple(normalize_value(v) for v in value)
    return str(value)


def normalize_rows(rows: list[tuple]) -> list[tuple]:
    return [tuple(normalize_value(v) for v in row) for row in rows]


def _matches(expected: list[tuple], actual: list[tuple], ordered: bool) -> bool:
    if ordered:
        return expected == actual
    return Counter(expected) == Counter(actual)


def compare_results(
    expected: QueryResult,
    actual: QueryResult,
    ordered: bool = False,
) -> bool:
    if expected is None or actual is None:
        return False
    if expected.error is not None or actual.error is not None:
        return False

    n = len(expected.columns)
    if n != len(actual.columns):
        return False
    if len(expected.rows) != len(actual.rows):
        return False

    exp_rows = normalize_rows(expected.rows)
    act_rows = normalize_rows(actual.rows)

    if not exp_rows and not act_rows:
        return True

    if _matches(exp_rows, act_rows, ordered):
        return True

    if n <= 1 or n > MAX_PERMUTATION_COLUMNS:
        return False

    # Prune: a permutation can only work if the multiset of values in each
    # expected column appears somewhere in the actual columns.
    exp_cols = [Counter(row[i] for row in exp_rows) for i in range(n)]
    act_cols = [Counter(row[i] for row in act_rows) for i in range(n)]
    candidates = [
        [j for j in range(n) if act_cols[j] == exp_cols[i]] for i in range(n)
    ]
    if any(not c for c in candidates):
        return False

    for perm in permutations(range(n)):
        # perm[i] = which actual column supplies expected column i
        if any(perm[i] not in candidates[i] for i in range(n)):
            continue
        permuted = [tuple(row[perm[i]] for i in range(n)) for row in act_rows]
        if _matches(exp_rows, permuted, ordered):
            return True

    return False


def result_summary(result: QueryResult, max_rows: int = 20) -> dict:
    """Compact, JSON-safe view of a result for the report.

    Only ever applied to results already held on the Python side. Nothing from
    here is sent to Claude.
    """
    if result is None:
        return {"error": "no result"}
    if result.error is not None:
        return {"error": result.error, "sqlstate": result.sqlstate}
    rows = [
        [_jsonable(v) for v in row] for row in result.rows[:max_rows]
    ]
    return {
        "columns": list(result.columns),
        "row_count": len(result.rows),
        "rows": rows,
        "truncated": len(result.rows) > max_rows,
    }


def _jsonable(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return str(value)


def compare_row_subset(
    expected: QueryResult,
    actual: QueryResult,
    ordered: bool = False,
) -> bool:
    """Did the query select the right ROWS, ignoring extra columns?

    "Which tasks are currently blocked?" has no single right column list. Claude
    answered `SELECT id, name, workflow_id, assigned_user_id, due_date`; the
    ground truth is `SELECT name`. The filter was identical -- the same seven
    tasks -- but strict comparison calls that a failure.

    Scoring it as wrong would understate the semantic layer badly, since the
    hard part (which rows) was right and the easy part (which columns) is
    genuinely ambiguous in the question. Scoring it as right would hide real
    errors. So it is reported as a SEPARATE metric, and the failure is
    classified EXTRA_COLUMNS rather than being folded into the accuracy number.

    True when every expected column can be matched to some actual column with
    the same values in the same row order.
    """
    if expected is None or actual is None:
        return False
    if expected.error is not None or actual.error is not None:
        return False
    if len(actual.columns) < len(expected.columns):
        return False
    if len(expected.rows) != len(actual.rows):
        return False

    exp_rows = normalize_rows(expected.rows)
    act_rows = normalize_rows(actual.rows)
    if not exp_rows and not act_rows:
        return True

    n_exp = len(expected.columns)
    n_act = len(actual.columns)

    exp_cols = [[row[i] for row in exp_rows] for i in range(n_exp)]
    act_cols = [[row[j] for row in act_rows] for j in range(n_act)]

    if not ordered:
        # Rows may come back in a different order. Align on the first expected
        # column, then require the rest to agree under that same alignment.
        exp_tuples = [tuple(row) for row in exp_rows]
        used: set[int] = set()
        chosen: list[int] = []
        for i in range(n_exp):
            for j in range(n_act):
                if j in used:
                    continue
                if Counter(act_cols[j]) == Counter(exp_cols[i]):
                    used.add(j)
                    chosen.append(j)
                    break
            else:
                return False
        projected = [tuple(row[j] for j in chosen) for row in act_rows]
        return Counter(projected) == Counter(exp_tuples)

    used = set()
    chosen = []
    for i in range(n_exp):
        for j in range(n_act):
            if j not in used and act_cols[j] == exp_cols[i]:
                used.add(j)
                chosen.append(j)
                break
        else:
            return False
    projected = [tuple(row[j] for j in chosen) for row in act_rows]
    return projected == [tuple(row) for row in exp_rows]
