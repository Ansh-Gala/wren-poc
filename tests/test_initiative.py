"""Which columns identify an initiative, and what colour its row is.

Positional throughout, for the reason the rest of the presentation layer is:
`columns` does not survive redaction, so the frontend has only indices to go
on, and a result may carry one column name twice.
"""

from __future__ import annotations

import pytest

from pipeline.initiative import (
    colour_class, colours_from_result, indices, with_initiative)


@pytest.mark.parametrize("value,expected", [
    # The initiative table stores the name.
    ("Black", "a_bl"), ("Red", "b_re"), ("Yellow", "c_ye"),
    ("Green", "d_gr"), ("White", "e_wh"),
    # The task table stores the class directly, so it passes through.
    ("a_bl", "a_bl"), ("e_wh", "e_wh"),
    # Case and padding are what a text column actually holds.
    ("  black  ", "a_bl"), ("GREEN", "d_gr"),
])
def test_a_stored_colour_becomes_the_class_the_app_already_uses(value, expected):
    assert colour_class(value) == expected


@pytest.mark.parametrize("value", [None, "", "   ", "nocolor", "purple", 7])
def test_an_unrecognised_colour_draws_no_bar_rather_than_a_wrong_one(value):
    """A wrong class would state a priority the data does not.

    nocolor is the case that matters: the frontend renders both it and e_wh as
    "White", so the name -> class direction cannot recover it, and guessing
    would paint an uncoloured initiative white as though someone had chosen
    that.
    """
    assert colour_class(value) is None


def test_the_positions_are_found_by_name_and_returned_as_indices():
    where = indices(["business_unit", "initiative_ref_id",
                     "initiative_id", "initiative_color"])
    assert where == {"id": 2, "ref_id": 1, "colour": 3}


def test_the_task_table_spells_the_id_bo_id():
    assert indices(["task_id", "bo_id"])["id"] == 1


def test_a_result_with_no_initiative_says_so_rather_than_guessing():
    assert indices(["task_id", "task_status"]) == {
        "id": None, "ref_id": None, "colour": None}
    assert indices(None) == {"id": None, "ref_id": None, "colour": None}


def test_a_repeated_name_takes_the_first_position():
    """A join projecting the id from both sides. First is the leading table."""
    assert indices(["initiative_id", "initiative_id"])["id"] == 0


def test_a_projected_colour_is_used_and_nothing_is_queried():
    result = {"columns": ["initiative_id", "initiative_color"],
              "rows": [[112, "Black"], [109, "Green"], [131, "White"]]}
    # settings=None would make a lookup impossible, so a colour coming back
    # proves the projected value was used.
    out = with_initiative(result, result["columns"], None)
    assert out["colours"] == {"112": "a_bl", "109": "d_gr", "131": "e_wh"}


def test_rows_whose_colour_is_unknown_are_left_out_of_the_map():
    """Absent from the map, not null in it: the frontend draws what is there."""
    result = {"columns": ["initiative_id", "initiative_color"],
              "rows": [[112, "Black"], [109, None], [131, "chartreuse"]]}
    assert colours_from_result(result, indices(result["columns"])) == {"112": "a_bl"}


def test_an_aggregate_gets_positions_but_no_colours_and_no_lookup():
    """21 of 73 benchmark turns are aggregates. There is nothing to open."""
    result = {"columns": ["initiative_status", "count"],
              "rows": [["Active", 196], ["Closed", 95]]}
    out = with_initiative(result, result["columns"], None)
    assert out["initiative"] == {"id": None, "ref_id": None, "colour": None}
    assert "colours" not in out


def test_the_rows_and_columns_are_never_touched():
    result = {"columns": ["initiative_id", "initiative_color"],
              "rows": [[112, "Black"]], "row_count": 1}
    out = with_initiative(result, result["columns"], None)
    assert out["columns"] == result["columns"]
    assert out["rows"] == result["rows"]
    assert out["row_count"] == 1


def test_a_clarification_passes_through():
    assert with_initiative(None, None, None) is None
    assert with_initiative("not a dict", None, None) == "not a dict"


def test_the_lookup_is_skipped_when_there_is_no_initiative_id():
    """No id means no query. The enrichment is new I/O on the answer path."""
    calls = []

    class Boom:
        statement_timeout_ms = 5000

    result = {"columns": ["task_id"], "rows": [[1]]}
    out = with_initiative(result, result["columns"], Boom())
    assert "colours" not in out
    assert calls == []


def test_a_failed_lookup_loses_the_bar_and_not_the_answer(monkeypatch):
    from pipeline import initiative
    from pipeline.models import QueryResult

    monkeypatch.setattr(
        "database.connection.run_readonly",
        lambda *a, **k: QueryResult(columns=[], rows=[], duration_ms=1.0,
                                    error="boom", sqlstate="57014"))

    result = {"columns": ["initiative_id"], "rows": [[112]]}
    out = initiative.with_initiative(result, result["columns"],
                                     type("S", (), {"statement_timeout_ms": 5000})())
    assert out["initiative"]["id"] == 0
    assert "colours" not in out
    assert out["rows"] == [[112]]


def test_only_integers_reach_the_lookup_sql(monkeypatch):
    """run_readonly takes a statement and no parameters, so the ids are
    interpolated. Anything that is not an integer is dropped before that."""
    seen = {}
    from pipeline import initiative
    from pipeline.models import QueryResult

    def capture(settings, sql, timeout=None, **kw):
        seen["sql"] = sql
        return QueryResult(columns=["initiative_id", "initiative_color"],
                           rows=[(112, "Black")], duration_ms=1.0)

    monkeypatch.setattr("database.connection.run_readonly", capture)
    result = {"columns": ["initiative_id"],
              "rows": [[112], ["'; DROP TABLE x --"], [None], [109], [112]]}
    out = initiative.with_initiative(
        result, result["columns"], type("S", (), {"statement_timeout_ms": 5000})())

    assert "DROP" not in seen["sql"]
    assert "IN (112, 109)" in seen["sql"], seen["sql"]
    assert out["colours"] == {"112": "a_bl"}


def test_both_new_fields_survive_debug_being_off():
    """The whole point. redact.public_response is a whitelist, so a field not
    named there is dropped -- which is how column_order shipped inert."""
    from pipeline.redact import public_response

    full = {
        "question": "Show the AR_NPD_Shirting items",
        "generated_sql": "SELECT ... -- must not survive",
        "result": {
            "columns": ["initiative_id"],
            "column_labels": ["Initiative Id"],
            "rows": [[112]], "row_count": 1, "truncated": False,
            "initiative": {"id": 0, "ref_id": None, "colour": None},
            "colours": {"112": "a_bl"},
        },
    }
    out = public_response(full)
    assert out["result"]["initiative"] == {"id": 0, "ref_id": None, "colour": None}
    assert out["result"]["colours"] == {"112": "a_bl"}
    assert "columns" not in out["result"]
    assert "generated_sql" not in out
