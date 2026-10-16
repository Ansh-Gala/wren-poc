"""Reading the chart the model asked for: Drupal's ResponseParser::parseChart."""

from __future__ import annotations

import json

import pytest

from claude.parser import chart_sql, parse_chart


def reply(chart, **extra) -> str:
    return json.dumps({"sql": "SELECT 1", "chart": chart, **extra})


GOOD = {"type": "groupedColumn", "category": " department ", "values": ["open_tasks "]}


def test_no_chart_is_none():
    assert parse_chart('{"sql": "SELECT 1"}') is None
    assert parse_chart(reply(None)) is None
    assert parse_chart(reply(False)) is None


def test_a_good_chart_is_read_and_trimmed():
    assert parse_chart(reply(GOOD)) == {"type": "groupedColumn", "category": "department",
                                        "values": ["open_tasks"]}


@pytest.mark.parametrize("chart,code", [
    (True, "bad_shape"), ([1, 2], "bad_shape"), ({}, "bad_shape"),
    ({**GOOD, "type": "treemap"}, "bad_type"),
    ({**GOOD, "category": "  "}, "bad_category"),
    ({**GOOD, "values": []}, "bad_values"),
    ({**GOOD, "values": ["a", " "]}, "bad_values"),
    ({**GOOD, "values": [f"v{i}" for i in range(13)]}, "bad_values"),
    ({**GOOD, "type": "pie", "values": ["a", "b"]}, "pie_values"),
    ({**GOOD, "sql": 7}, "bad_sql"),
    ({**GOOD, "series": "status", "values": ["a", "b"]}, "bad_series"),
    ({**GOOD, "type": "pie", "series": "status"}, "bad_series"),
])
def test_an_unusable_chart_says_why(chart, code):
    assert parse_chart(reply(chart)) == {"invalid": code}


def test_a_chart_in_a_clarification_is_refused():
    text = json.dumps({"clarify": "Which one?", "chart": GOOD})
    assert parse_chart(text) == {"invalid": "in_clarify"}


def test_title_series_and_sql_are_kept():
    chart = {**GOOD, "series": " status ", "title": " " + "t" * 100,
             "sql": " SELECT 2 ", "values": ["n"]}
    parsed = parse_chart(reply(chart))
    assert parsed["series"] == "status"
    assert parsed["title"] == "t" * 80
    assert parsed["sql"] == "SELECT 2"


def test_a_bad_colour_is_dropped_on_its_own():
    chart = {**GOOD, "colors": {"Sales": "#12ab3C", "Design": "red", " ": "#000000", "x": 5}}
    assert parse_chart(reply(chart))["colors"] == {"Sales": "#12ab3C"}


def test_the_chart_query_is_cleaned_like_the_main_one():
    assert chart_sql("SELECT 1; -- note") == "SELECT 1"
    assert chart_sql("   ") is None
    assert chart_sql("count them") is None
