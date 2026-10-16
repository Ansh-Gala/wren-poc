"""What the chart check draws, and every reason it refuses to.

The cases are the Drupal port's tests/chart/check.php, one for one, so the two
implementations are held to the same answers. Python and PHP were also run on
8,000 generated cases and agreed on every one (16 October 2026).
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from pipeline import chart_check as cc


def source(columns, rows, truncated=False):
    """A result the way the summary returns one: every cell a string."""
    return {"columns": columns, "rows": rows, "truncated": truncated}


def build(chart, src):
    labels = [c.replace("_", " ").title() for c in src.get("columns") or []]
    return cc.build(chart, src, labels)


def reason(chart, src):
    return build(chart, src)["reason"]


BARS = {"type": "groupedColumn", "category": "department", "values": ["open_tasks"]}
BY_DEPT = source(["department", "open_tasks", "closed_tasks"],
                 [["Sales", "12", "3"], ["Design Team", "7", "0"], ["Sourcing", "4", "1"]])
PIE = {"type": "pie", "category": "colour", "values": ["n"]}
TREND = {"type": "line", "category": "week_start", "values": ["open_tasks"]}


def weeks(dates):
    return source(["week_start", "open_tasks"], [[d, "5"] for d in dates])


def slices(n):
    return source(["colour", "n"], [[f"s{i}", "1"] for i in range(1, n + 1)])


# ------------------------------------------------------------- what it draws --

def test_a_bar_chart_is_built():
    assert build(BARS, BY_DEPT) == {"chart": {
        "type": "groupedColumn", "labels": ["Department", "Open Tasks"],
        "rows": [["Sales", 12], ["Design Team", 7], ["Sourcing", 4]]}, "reason": "ok"}


def test_the_title_rides_along():
    chart = build({**BARS, "title": "Open tasks by department"}, BY_DEPT)["chart"]
    assert chart["title"] == "Open tasks by department"


def test_names_match_without_regard_to_case():
    chart = {"type": "groupedColumn", "category": "DEPARTMENT", "values": ["Open_Tasks"]}
    assert reason(chart, BY_DEPT) == "ok"


def test_only_the_chosen_columns_travel_even_from_a_wide_source():
    columns = [f"c{i}" for i in range(20)]
    rows = [["a" if i == 0 else str(i) for i in range(20)],
            ["b" if i == 0 else str(i) for i in range(20)]]
    chart = {"type": "groupedBar", "category": "c0", "values": ["c19"]}
    assert build(chart, source(columns, rows))["chart"]["rows"] == [["a", 19], ["b", 19]]


def test_the_rows_keep_the_order_the_query_returned():
    rows = build(BARS, source(["department", "open_tasks"], [["Z", "1"], ["A", "2"], ["M", "3"]]))
    assert [r[0] for r in rows["chart"]["rows"]] == ["Z", "A", "M"]


# ------------------------------------------------------------------ numbers --

def test_numeric_strings_become_numbers():
    chart = {"type": "groupedColumn", "category": "d", "values": ["n"]}
    built = build(chart, source(["d", "n"], [["a", "12"], ["b", "12.50"], ["c", "-3"], ["e", "1e3"]]))
    got = [r[1] for r in built["chart"]["rows"]]
    assert got == [12, 12.5, -3, 1000.0]
    assert [type(v) for v in got] == [int, float, int, float]


def test_a_null_in_a_line_chart_stays_a_gap():
    chart = {"type": "line", "category": "d", "values": ["n"]}
    built = build(chart, source(["d", "n"], [["2026-08-03", "4"], ["2026-08-10", None],
                                             ["2026-08-17", "6"]]))
    assert [r[1] for r in built["chart"]["rows"]] == [4, None, 6]


@pytest.mark.parametrize("kind", ["stackedColumn", "normalizedBar", "stackedArea", "pie", "donut"])
def test_a_null_is_refused_where_it_would_read_as_zero(kind):
    chart = {"type": kind, "category": "d", "values": ["n"]}
    src = source(["d", "n"], [["2026-08-03", "4"], ["2026-08-10", None], ["2026-08-17", "6"]])
    assert reason(chart, src) == "null_value"


@pytest.mark.parametrize("cell", ["", "NaN", "Infinity", "-Infinity", "12 kg", " 12"])
def test_a_cell_that_is_not_a_number_is_refused(cell):
    assert reason(BARS, source(["department", "open_tasks"], [["Sales", "3"], ["Design", cell]])) \
        == "not_numeric"


def test_one_text_cell_refuses_the_whole_chart():
    src = source(["department", "open_tasks"], [["A", "4"], ["B", "x"], ["C", "7"]])
    assert reason(BARS, src) == "not_numeric"


def test_a_value_column_with_no_number_is_refused():
    chart = {"type": "line", "category": "d", "values": ["n"]}
    assert reason(chart, source(["d", "n"], [["2026-01-01", None], ["2026-01-02", None]])) \
        == "no_numbers"


def test_a_missing_value_never_becomes_zero():
    cases = [
        ({"type": "line", "category": "d", "values": ["n"]},
         source(["d", "n"], [["2026-01-01", None], ["2026-01-02", "5"]])),
        ({"type": "groupedBar", "category": "d", "values": ["n", "m"]},
         source(["d", "n", "m"], [["a", None, "1"], ["b", "2", None]])),
    ]
    zeros = sum(1 for chart, src in cases for row in build(chart, src)["chart"]["rows"]
                for cell in row[1:] if cell == 0 and cell is not None)
    assert zeros == 0


def test_a_real_zero_stays_zero():
    chart = {"type": "groupedColumn", "category": "department", "values": ["closed_tasks"]}
    assert build(chart, BY_DEPT)["chart"]["rows"][1][1] == 0


# ---------------------------------------------------------------- pie charts --

def test_a_negative_slice_is_refused():
    assert reason(PIE, source(["colour", "n"], [["Green", "4"], ["Red", "-1"]])) == "negative_slice"


def test_a_zero_slice_is_drawn():
    assert reason(PIE, source(["colour", "n"], [["Green", "4"], ["Red", "0"]])) == "ok"


def test_a_pie_of_twelve_stays_a_pie_with_no_note():
    built = build(PIE, slices(12))
    assert built["chart"]["type"] == "pie" and "note" not in built


def test_a_pie_of_thirteen_is_drawn_as_columns_and_says_why():
    built = build(PIE, slices(13))
    assert built["chart"]["type"] == "groupedColumn"
    assert built["note"] == ("Drawn as a column chart: a pie can show at most 12 parts, "
                             "and this answer has 13.")


WEEKLY = source(["week", "n"], [[(date(2026, 3, 2) + timedelta(weeks=i)).isoformat(), "4"]
                                for i in range(25)])


def test_a_pie_of_25_weeks_is_drawn_as_a_line():
    assert build({**PIE, "category": "week"}, WEEKLY)["chart"]["type"] == "line"


def test_a_donut_says_donut():
    built = build({**PIE, "type": "donut", "category": "week"}, WEEKLY)
    assert built["note"] == ("Drawn as a line chart: a donut can show at most 12 parts, "
                             "and this answer has 25.")


def test_too_many_slices_or_a_truncated_pie_is_still_refused():
    assert reason(PIE, slices(101)) == "rows"
    assert reason(PIE, source(["colour", "n"], slices(13)["rows"], truncated=True)) == "rows"


# ---------------------------------------------------------------- time order --

@pytest.mark.parametrize("dates,want", [
    (["2026-08-03", "2026-08-10", "2026-08-17"], "ok"),
    (["2026-08-03 00:00:00+05:30", "2026-08-10 00:00:00+05:30"], "ok"),
    (["2024", "2025", "2026"], "ok"),
    (["2026-08-10", "2026-08-03", "2026-08-17"], "not_chronological"),
    (["2026-08-17", "2026-08-10", "2026-08-03"], "not_chronological"),
    (["W1 - Aug 26", "W2 - Aug 26"], "not_chronological"),
    (["Jan", "Feb", "Mar"], "not_chronological"),
    (["2026-08-03", None], "not_chronological"),
])
def test_time_order(dates, want):
    assert reason(TREND, weeks(dates)) == want


def test_the_same_week_twice_is_refused():
    chart = {"type": "area", "category": "week_start", "values": ["open_tasks"]}
    assert reason(chart, weeks(["2026-08-03", "2026-08-03 00:00:00"])) == "not_chronological"


def test_a_bar_chart_is_never_order_checked():
    assert reason(BARS, source(["department", "open_tasks"], [["Zed", "1"], ["Abe", "2"]])) == "ok"


# ------------------------------------------------------------ what it refuses --

def test_malformed_sources():
    assert reason(BARS, {"columns": ["department", "open_tasks"]}) == "malformed"
    assert reason(BARS, {"columns": {"a": "department"}, "rows": [["x"]]}) == "malformed"
    assert reason(BARS, source(["department", "open_tasks"], [["Sales", "1"], ["Design"]])) \
        == "malformed"
    assert cc.build(BARS, BY_DEPT, ["Department"])["reason"] == "malformed"


def test_row_counts():
    assert reason(BARS, source(["department", "open_tasks"], [["Sales", "1"]])) == "ok"
    assert reason(TREND, weeks(["2026-08-03"])) == "rows"
    assert reason(PIE, source(["colour", "n"], [["Green", "4"]])) == "rows"
    assert reason(BARS, source(["department", "open_tasks"], [])) == "rows"
    many = lambda n: source(["department", "open_tasks"], [[f"d{i}", "1"] for i in range(1, n + 1)])
    assert reason(BARS, many(101)) == "rows"
    assert reason(BARS, many(100)) == "ok"
    assert reason(BARS, source(BY_DEPT["columns"], BY_DEPT["rows"], truncated=True)) == "rows"


def test_column_names():
    assert reason({"type": "groupedBar", "category": "department", "values": ["nope"]}, BY_DEPT) \
        == "unknown_column"
    assert reason(BARS, source(["department", "open_tasks", "Open_Tasks"],
                               [["A", "1", "2"], ["B", "3", "4"]])) == "unknown_column"
    assert reason({"type": "groupedBar", "category": "open_tasks", "values": ["open_tasks"]},
                  BY_DEPT) == "same_column"
    assert reason({"type": "groupedBar", "category": "department",
                   "values": ["open_tasks", "OPEN_TASKS"]}, BY_DEPT) == "same_column"


@pytest.mark.parametrize("width,want", [(12, "ok"), (13, "series")])
def test_at_most_twelve_values(width, want):
    names = [f"v{i}" for i in range(1, width + 1)]
    src = source(["d"] + names, [["x"] + ["1"] * width, ["y"] + ["1"] * width])
    assert reason({"type": "groupedBar", "category": "d", "values": names}, src) == want


def test_categories():
    rows = lambda r: build(BARS, source(["department", "open_tasks"], r))
    assert rows([["Sales", "1"], [None, "2"]])["chart"]["rows"] == [["Sales", 1], ["Not set", 2]]
    assert rows([["Sales", "1"], ["  ", "2"]])["chart"]["rows"][1][0] == "Not set"
    assert rows([[None, "1"], ["", "2"]])["reason"] == "not_one_row_per_category"
    assert rows([["Not set", "1"], [None, "2"]])["reason"] == "not_one_row_per_category"
    assert rows([["Sales", "1"], [["x"], "2"]])["reason"] == "malformed"
    assert rows([["Sales", "1"], ["Sales", "2"]])["reason"] == "not_one_row_per_category"


def test_a_chart_over_64_kb():
    src = source(["department", "open_tasks"], [["x" * 700 + str(i), "1"] for i in range(1, 101)])
    assert reason(BARS, src) == "too_big"


# ------------------------------------------------ long rows, pivoted by series

LONG = source(["department", "status", "n"],
              [["Sales", "open", "3"], ["Sales", "closed", "5"], ["Design", "open", "2"]])
BY_STATUS = {"type": "stackedColumn", "category": "department", "series": "status", "values": ["n"]}


def test_long_rows_become_one_row_per_category():
    assert build(BY_STATUS, LONG)["chart"] == {
        "type": "stackedColumn", "labels": ["Department", "open", "closed"],
        "rows": [["Sales", 3, 5], ["Design", 2, None]]}


def test_a_missing_pair_is_a_gap_but_a_real_null_is_not():
    assert reason(BY_STATUS, LONG) == "ok"
    real_null = source(["department", "status", "n"], [["Sales", "open", None], ["Design", "open", "2"]])
    assert reason(BY_STATUS, real_null) == "null_value"


def test_a_null_series_name_is_drawn_as_not_set():
    src = source(["department", "status", "n"], [["Sales", None, "1"], ["Design", "open", "2"]])
    assert build(BY_STATUS, src)["chart"]["labels"] == ["Department", "Not set", "open"]


def _by_week(parts):
    return source(["week", "department", "n"],
                  [[f"2026-08-1{w}", f"d{i}", "1"] for w in range(3) for i in range(1, parts + 1)])


DEPT_LINE = {"type": "line", "category": "week", "series": "department", "values": ["n"]}


def test_series_limits():
    assert len(build(DEPT_LINE, _by_week(11))["chart"]["labels"]) == 12
    assert reason(DEPT_LINE, _by_week(12)) == "ok"
    assert reason(DEPT_LINE, _by_week(13)) == "series"


def test_pivot_refusals():
    twice = source(["department", "status", "n"], [["Sales", "open", "1"], ["Sales", "open", "2"]])
    assert reason(BY_STATUS, twice) == "not_one_row_per_category"
    assert reason({**BY_STATUS, "series": "nope"}, LONG) == "unknown_column"
    assert reason({**BY_STATUS, "series": "department"}, LONG) == "same_column"


def test_a_pivoted_line_is_still_checked_for_time_order():
    line = {"type": "line", "category": "week", "series": "status", "values": ["n"]}
    backwards = source(["week", "status", "n"], [["2026-08-10", "open", "1"], ["2026-08-03", "open", "2"]])
    assert reason(line, backwards) == "not_chronological"
    forwards = source(["week", "status", "n"], [["2026-08-03", "open", "1"],
                                                ["2026-08-03", "closed", "4"],
                                                ["2026-08-10", "open", "2"]])
    assert build(line, forwards)["chart"]["rows"] == [["2026-08-03", 1, 4], ["2026-08-10", 2, None]]


# ------------------------------------------------------------------ colours --

GREEN, RED = cc.STATUS_COLOURS["green"], cc.STATUS_COLOURS["red"]
BY_COLOUR = source(["colour", "n"], [["Green", "4"], ["Yellow", "2"], ["Red", "1"],
                                     ["Black", "3"], ["White", "1"]])


def test_status_slices_take_the_status_colours():
    assert build(PIE, BY_COLOUR)["chart"]["colors"] == {
        "Green": GREEN, "Yellow": cc.STATUS_COLOURS["yellow"], "Red": RED,
        "Black": cc.STATUS_COLOURS["black"], "White": cc.STATUS_COLOURS["white"]}


def test_status_series_take_the_status_colours():
    chart = {"type": "stackedColumn", "category": "department", "values": ["open_green", "open_red"]}
    src = source(["department", "open_green", "open_red"], [["Sales", "1", "2"], ["Design", "3", "4"]])
    assert build(chart, src)["chart"]["colors"] == {"Open Green": GREEN, "Open Red": RED}


def test_the_model_colours():
    assert build({**PIE, "colors": {"Green": "#000000"}}, BY_COLOUR)["chart"]["colors"]["Green"] == GREEN
    assert build({**BARS, "colors": {"open_tasks": "#123456"}}, BY_DEPT)["chart"]["colors"] \
        == {"Open Tasks": "#123456"}
    assert build({**BARS, "colors": {"sales": "#abcdef"}}, BY_DEPT)["chart"]["colors"] \
        == {"Sales": "#abcdef"}
    assert build({**BY_STATUS, "colors": {"open": "#00aa00"}}, LONG)["chart"]["colors"] \
        == {"open": "#00aa00"}


def test_a_line_takes_no_colour_per_category():
    built = build({**TREND, "colors": {"2026-08-03": "#abcdef"}}, weeks(["2026-08-03", "2026-08-10"]))
    assert "colors" not in built["chart"]


def test_the_apps_colour_codes_take_the_status_colours():
    src = source(["initiative_color", "n"], [["a_bl", "9"], ["d_gr", "5"], ["E_WH", "1"],
                                             ["b_re", "1"], ["c_ye", "1"]])
    assert build({**PIE, "category": "initiative_color"}, src)["chart"]["colors"] == {
        "a_bl": cc.STATUS_COLOURS["black"], "d_gr": GREEN, "E_WH": cc.STATUS_COLOURS["white"],
        "b_re": RED, "c_ye": cc.STATUS_COLOURS["yellow"]}


@pytest.mark.parametrize("labels", [["xa_bl", "a_bl2"], ["Red or Black", "Other"],
                                    ["Reduced", "Greenfield"]])
def test_labels_that_only_look_like_a_status_get_none(labels):
    src = source(["colour", "n"], [[labels[0], "1"], [labels[1], "2"]])
    assert "colors" not in build(PIE, src)["chart"]


# ------------------------------------------------------------------- notes --

@pytest.mark.parametrize("why,want", [
    (None, None), ("ok", None), ("no_answer", None),
    ("rows", cc.NOTES["rows"]),
    ("chart_sql_timeout", cc.NOTES["chart_sql"]),
    ("config_bad_type", cc.NOTES["other"]),
])
def test_notes(why, want):
    assert cc.note(why) == want
