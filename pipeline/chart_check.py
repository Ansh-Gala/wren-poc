"""Turns the model's chart config and a result into the chart the page draws.

Ported from the Drupal port's ChartCheck. The model decides whether a chart is
wanted and names its columns; this only refuses what the rows cannot honestly
show. Any failure drops the chart and leaves the answer alone, so every check
returns a reason rather than raising.

The built chart is the only chart data that leaves the server: the chosen
columns, under their labels, with real numbers, in the order the SQL returned
them. No column names, positions, types or SQL.
"""

from __future__ import annotations

import json
import math
import re
from datetime import datetime

# The chart types the page can draw: AG Charts Community types only.
TYPES = (
    "groupedColumn", "stackedColumn", "normalizedColumn",
    "groupedBar", "stackedBar", "normalizedBar",
    "line", "area", "stackedArea", "normalizedArea",
    "pie", "donut",
)
# Types that take exactly one value column.
ONE_VALUE_TYPES = ("pie", "donut")
# Types that may be drawn from one row: a single bar still reads. A pie of one
# slice or a line of one point says nothing, so the rest need two rows.
ONE_ROW_TYPES = ("groupedColumn", "stackedColumn", "normalizedColumn",
                 "groupedBar", "stackedBar", "normalizedBar")
# Types drawn along a time axis, so their rows must be in time order.
TIME_TYPES = ("line", "area", "stackedArea", "normalizedArea")
# Types where a NULL value reads correctly, as a gap or a missing bar. The
# others would draw it as nothing, which reads as zero -- a claim the data did
# not make.
GAP_TYPES = ("line", "area", "groupedColumn", "groupedBar")

MAX_ROWS = 100
MAX_PIE_ROWS = 12
# Lines, bars or stack parts in one chart: as many as a pie has parts.
MAX_SERIES = 12
# Bytes of the built chart, JSON-encoded as PHP encodes it.
MAX_BYTES = 65536
# Statement timeout for the chart's own query: a chart is never worth a slow
# answer.
TIMEOUT_MS = 20000
TITLE_LENGTH = 80
# The label of a NULL or blank category: a real group, drawn under a name.
# Only labels are named; a missing number is never filled in.
EMPTY_LABEL = "Not set"

# A finite number as Postgres prints one. NaN, Infinity and blanks fail.
_NUMBER = re.compile(r"^-?(\d+\.?\d*|\.\d+)([eE][-+]?\d+)?$")
_ISO_TIME = re.compile(
    r"^\d{4}-\d{2}-\d{2}([ T]\d{2}:\d{2}(:\d{2}(\.\d+)?)?([+-]\d{2}(:?\d{2})?|Z)?)?$")
_WHOLE = re.compile(r"^-?\d+$")
COLOUR = re.compile(r"^#[0-9a-fA-F]{6}$")

# What the reader is told when the chart asked for is not drawn.
NOTES = {
    "rows": "No chart: this answer has too many or too few rows to draw.",
    "series": "No chart: it would need too many lines or bars to read. Ask for one "
              "measure, or fewer groups.",
    "config_bad_series": "No chart: it would need too many lines or bars to read. Ask "
                         "for one measure, or fewer groups.",
    "not_chronological": "No chart: the rows could not be put in date order.",
    "null_value": "No chart: some values are missing, and drawing them would show "
                  "zeros that are not there.",
    "chart_sql": "No chart: the numbers for the chart could not be fetched.",
    "other": "No chart could be drawn for this answer.",
}

# The colours a label is always drawn in come from product.yaml's `colours`:
# name -> {code, hex}, passed to build() as `palette`.
# PHP's trim(): only these characters, not every Unicode space.
PHP_TRIM = " \t\n\r\0\x0b"


def build(chart: dict, source: dict, labels: list, palette: dict | None = None) -> dict:
    """The chart, or why not: {"chart": built or None, "reason": "ok" or why},
    plus "note" when the type drawn is not the type asked for.

    ``palette`` is product.yaml's `colours`: a label naming one is always
    drawn in its hex, beating any colour the model chose."""
    columns, rows = source.get("columns"), source.get("rows")
    if not _is_list_of_rows(columns, rows) or not isinstance(labels, list) \
            or len(labels) != len(columns):
        return _no("malformed")

    # Long rows (category, series, value) become one row per category, one
    # column per series. A pair with no row is a gap, not a zero.
    gaps: set[str] = set()
    if "series" in chart:
        pivot = _pivot(chart, columns, rows, labels)
        if isinstance(pivot, str):
            return _no(pivot)
        chart, columns, rows, labels, gaps = pivot

    # A pie of more parts than a reader can tell apart is drawn as columns, or
    # as a line once its parts prove to be dates.
    asked = chart["type"]
    kind = asked
    if asked in ONE_VALUE_TYPES and len(rows) > MAX_PIE_ROWS:
        kind = "groupedColumn"
    limit = MAX_PIE_ROWS if kind in ONE_VALUE_TYPES else MAX_ROWS
    least = 1 if kind in ONE_ROW_TYPES else 2
    if source.get("truncated") or len(rows) < least or len(rows) > limit:
        return _no("rows")

    category = _position(columns, chart["category"])
    values = [_position(columns, name) for name in chart["values"]]
    if category is None or None in values:
        return _no("unknown_column")
    if category in values or len(set(values)) != len(values):
        return _no("same_column")
    if len(values) > MAX_SERIES:
        return _no("series")

    categories: list[str] = []
    for row in rows:
        label = row[category]
        if label is not None and not _is_scalar(label):
            return _no("malformed")
        label = EMPTY_LABEL if label is None or _php_str(label).strip(PHP_TRIM) == "" \
            else _php_str(label)
        # A NULL and a blank, or a real "Not set", land on one label: refused.
        if label in categories:
            return _no("not_one_row_per_category")
        categories.append(label)
    if kind != asked and _rising(categories):
        kind = "line"

    numbers = []
    for index in values:
        column = []
        for r, row in enumerate(rows):
            cell = row[index]
            if cell is None:
                if f"{r}:{index}" not in gaps and kind not in GAP_TYPES:
                    return _no("null_value")
                column.append(None)
                continue
            number = _number(cell)
            if number is None:
                return _no("not_numeric")
            column.append(number)
        if all(v is None for v in column):
            return _no("no_numbers")
        numbers.append(column)

    if kind in ONE_VALUE_TYPES and min(v for v in numbers[0] if v is not None) < 0:
        return _no("negative_slice")
    if kind in TIME_TYPES and not _rising(categories):
        return _no("not_chronological")

    built: dict = {"type": kind}
    if "title" in chart:
        built["title"] = chart["title"]
    built["labels"] = [_php_str(labels[category])] + [_php_str(labels[i]) for i in values]
    built["rows"] = [[categories[r]] + [column[r] for column in numbers] for r in range(len(rows))]

    # Where each drawn label may find a colour: under itself, or under the
    # column it came from. Categories are the parts drawn only with one value
    # and no time axis.
    names: dict[str, list] = {}
    for i, index in enumerate(values):
        names[built["labels"][i + 1]] = [built["labels"][i + 1], columns[index]]
    if len(values) == 1 and kind not in TIME_TYPES:
        for label in categories:
            names[label] = [label]
    colours = _colours(chart.get("colors") or {}, names, palette or {})
    if colours:
        built["colors"] = colours

    if len(_php_json(built)) > MAX_BYTES:
        return _no("too_big")
    if kind == asked:
        return {"chart": built, "reason": "ok"}
    note = (f"Drawn as a {'line' if kind == 'line' else 'column'} chart: a {asked} can show "
            f"at most {MAX_PIE_ROWS} parts, and this answer has {len(rows)}.")
    return {"chart": built, "reason": "ok", "note": note}


def note(reason: str | None) -> str | None:
    """What to tell the reader about a chart that was not drawn, or None:
    None when none was asked for, when it was drawn, and when there is no
    answer to draw from -- then the error or the question back says enough."""
    if reason is None or reason in ("ok", "no_answer", "config_in_clarify"):
        return None
    if reason.startswith("chart_sql_"):
        return NOTES["chart_sql"]
    return NOTES.get(reason, NOTES["other"])


# ------------------------------------------------------------------ helpers

def _colours(wanted: dict, names: dict, palette: dict) -> dict:
    """The colour of each drawn label that has one. A product colour always
    gets its own; any other label gets the model's, if it gave one under any
    of the label's names."""
    wanted = {str(k).lower(): v for k, v in wanted.items()}
    colours = {}
    for label, keys in names.items():
        colour = _status_colour(str(label), palette)
        for key in keys:
            colour = colour if colour is not None else wanted.get(str(key).lower())
        if colour is not None:
            colours[label] = colour
    return colours


def _status_colour(label: str, palette: dict) -> str | None:
    """A whole word only, so "Reduced" is not red, and exactly one: a label
    naming two colours is not either of them. Or a whole colour code."""
    hex_by_name, name_by_code = {}, {}
    for name, colour in palette.items():
        if not isinstance(colour, dict) or "hex" not in colour:
            continue
        hex_by_name[str(name).lower()] = str(colour["hex"])
        if "code" in colour:
            name_by_code[str(colour["code"]).lower()] = str(name).lower()
    if not hex_by_name:
        return None
    code = label.strip(PHP_TRIM).lower()
    if code in name_by_code:
        return hex_by_name[name_by_code[code]]
    words = re.compile(r"\b(" + "|".join(re.escape(n) for n in hex_by_name) + r")\b", re.IGNORECASE)
    found = {m.lower() for m in words.findall(label)}
    return hex_by_name[found.pop()] if len(found) == 1 else None


def _pivot(chart: dict, columns: list, rows: list, labels: list):
    """Long rows to wide ones. [chart, columns, rows, labels, gaps], or the
    reason it cannot be built. gaps marks "row:column" cells no row filled."""
    category = _position(columns, chart["category"])
    series = _position(columns, chart["series"])
    value = _position(columns, chart["values"][0]) if len(chart["values"]) == 1 else None
    if category is None or series is None or value is None:
        return "unknown_column"
    if len({category, series, value}) != 3:
        return "same_column"

    names: list[str] = []
    categories: dict[str, object] = {}
    cells: dict[str, dict] = {}
    for row in rows:
        if (row[series] is not None and not _is_scalar(row[series])) or \
                (row[category] is not None and not _is_scalar(row[category])):
            return "malformed"
        name = EMPTY_LABEL if row[series] is None or _php_str(row[series]).strip(PHP_TRIM) == "" \
            else _php_str(row[series])
        key = "\0" if row[category] is None else _php_str(row[category])
        if key not in categories:
            categories[key] = row[category]
            cells[key] = {}
        if name not in names:
            names.append(name)
        if name in cells[key]:
            return "not_one_row_per_category"
        cells[key][name] = row[value]
    if len(names) > MAX_SERIES:
        return "series"

    wide, gaps = [], set()
    for r, key in enumerate(categories):
        line = [categories[key]]
        for s, name in enumerate(names):
            if name in cells[key]:
                line.append(cells[key][name])
            else:
                line.append(None)
                gaps.add(f"{r}:{s + 1}")
        wide.append(line)
    wide_columns = ["category"] + [f"series_{s}" for s in range(len(names))]
    chart = {k: v for k, v in chart.items() if k != "series"}
    chart["category"] = "category"
    chart["values"] = wide_columns[1:]
    return chart, wide_columns, wide, [labels[category]] + names, gaps


def _is_list_of_rows(columns, rows) -> bool:
    if not isinstance(columns, list) or not isinstance(rows, list):
        return False
    return all(isinstance(row, list) and len(row) == len(columns) for row in rows)


def _position(columns: list, name) -> int | None:
    """The one column with this name, ignoring case. A name two columns share
    is as unusable as one that matches none."""
    wanted = str(name).lower()
    found = [i for i, c in enumerate(columns) if str(c).lower() == wanted]
    return found[0] if len(found) == 1 else None


def _is_scalar(value) -> bool:
    return isinstance(value, (str, int, float, bool))


def _php_str(value) -> str:
    """A value as PHP's (string) cast writes it."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "1" if value else ""
    if isinstance(value, float):
        # PHP's precision=14, and its exponent form: 1.0E+15, 1.0E-5.
        text = format(value, ".14G")
        if "E" in text:
            mantissa, exponent = text.split("E")
            if "." not in mantissa:
                mantissa += ".0"
            text = f"{mantissa}E{exponent[0]}{int(exponent[1:])}"
        return text
    return str(value)


def _number(cell):
    """The cell as an int or float, or None when it is not a finite number.
    Never zero for a cell that is not a number."""
    if isinstance(cell, bool):
        return None
    if isinstance(cell, int):
        return cell
    if isinstance(cell, float):
        return cell if math.isfinite(cell) else None
    if not isinstance(cell, str) or not _NUMBER.match(cell):
        return None
    # PHP keeps a whole number as an int only when it reads back the same and
    # fits in 64 bits; anything else is a float.
    if _WHOLE.match(cell) and str(int(cell)) == cell and abs(int(cell)) <= 2**63 - 1:
        return int(cell)
    number = float(cell)
    return number if math.isfinite(number) else None


def _rising(categories: list) -> bool:
    """Whether the categories are provably in time order, oldest first. Only
    ISO dates or timestamps, or whole numbers (years), can be proven; labels
    such as "W5 - Aug 26" cannot. Strictly rising, so a repeat fails too."""
    keys = []
    for category in categories:
        text = str(category)
        if _WHOLE.match(text):
            keys.append(("n", int(text)))
        elif _ISO_TIME.match(text):
            moment = _timestamp(text)
            if moment is None:
                return False
            keys.append(("t", moment))
        else:
            return False
    if len({kind for kind, _ in keys}) != 1:
        return False
    return all(keys[i][1] > keys[i - 1][1] for i in range(1, len(keys)))


def _timestamp(text: str) -> float | None:
    """An ISO date or time as seconds, local time when no zone is given, as
    PHP's strtotime reads it."""
    try:
        moment = datetime.fromisoformat(text.replace(" ", "T", 1))
    except ValueError:
        return None
    return moment.timestamp()


def _php_json(value) -> str:
    """JSON as PHP's json_encode writes it by default: non-ASCII escaped and
    "/" escaped, which is what the size limit was measured on."""
    return json.dumps(value, ensure_ascii=True, separators=(",", ":")).replace("/", "\\/")


def _no(reason: str) -> dict:
    return {"chart": None, "reason": reason}
