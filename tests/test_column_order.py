"""Which columns matter, for a result whose columns the user did not choose.

Everything here is positional. A result may project the same name twice --
COUNT(*) twice, or a join taking business_object_ref_id from both sides -- and
the frontend keys its rows by position for exactly that reason, so a
name-based answer would have to be re-resolved by the caller and would be
wrong in the one case that matters.
"""

from __future__ import annotations

from pipeline.column_order import presentation


def test_named_columns_lead_in_the_order_the_file_gives_them():
    columns = ["business_unit", "business_object_status", "business_object_id"]
    out = presentation(columns, ["tms_business_object_flat"])
    # File order, not result order: id, then status, then unit.
    assert [columns[i] for i in out["order"]] == [
        "business_object_id", "business_object_status", "business_unit"]


def test_unlisted_columns_keep_their_own_order_after_the_named_ones():
    """A generated alias has never appeared in any registry and still has to
    be shown somewhere predictable."""
    columns = ["avg_delay_days", "business_object_id", "some_new_column"]
    out = presentation(columns, ["tms_business_object_flat"])
    assert [columns[i] for i in out["order"]] == [
        "business_object_id", "avg_delay_days", "some_new_column"]


def test_hidden_columns_are_positions_and_stay_inside_the_order():
    """Hidden is a display hint, not a deletion.

    The column is still in the result, still in `order`, and still exported --
    the frontend starts it collapsed. Dropping it from `order` would make the
    two lists disagree about how many columns there are.
    """
    columns = ["business_object_id", "business_object_note"]
    out = presentation(columns, ["tms_business_object_flat"])
    assert out["hidden"] == [1]
    assert sorted(out["order"]) == [0, 1]


def test_a_duplicated_column_name_gets_both_of_its_positions():
    columns = ["business_object_id", "business_object_id"]
    out = presentation(columns, ["tms_business_object_flat"])
    assert sorted(out["order"]) == [0, 1], "a repeated name must not collapse"


def test_an_unknown_table_leaves_the_result_untouched():
    columns = ["a", "b", "c"]
    out = presentation(columns, ["some_view_nobody_configured"])
    assert out["order"] == [0, 1, 2]
    assert out["hidden"] == []


def test_no_columns_is_not_an_error():
    """A clarification turn has no result and no columns."""
    assert presentation(None, None) == {"order": [], "hidden": []}
    assert presentation([], ["tms_task_flat"]) == {"order": [], "hidden": []}


def test_the_order_is_always_a_permutation_of_the_positions():
    """The invariant the frontend depends on: every column appears once."""
    columns = ["business_object_id", "workflow_id", "avg_delay_days",
               "business_object_status", "business_object_status"]
    out = presentation(columns, ["tms_business_object_flat"])
    assert sorted(out["order"]) == list(range(len(columns)))
    assert all(0 <= i < len(columns) for i in out["hidden"])


def test_the_first_configured_table_decides_for_a_join():
    """Not merged: a join's columns come from two tables, and merging their
    priority lists would invent an order neither file states."""
    columns = ["task_id", "business_object_id"]
    out = presentation(columns, ["tms_task_flat", "tms_business_object_flat"])
    assert [columns[i] for i in out["order"]] == ["task_id", "business_object_id"]


def test_labels_attaches_presentation_without_disturbing_anything():
    from pipeline.labels import with_presentation

    result = {"columns": ["business_object_note", "business_object_id"],
              "rows": [["n", 1]], "row_count": 1, "truncated": False}
    out = with_presentation(result, ["tms_business_object_flat"])

    assert out["column_order"] == [1, 0]
    assert out["hidden_columns"] == [0]
    assert out["columns"] == result["columns"], "columns must be untouched"
    assert out["rows"] == result["rows"], "rows must be untouched"


def test_a_clarification_passes_through_unchanged():
    from pipeline.labels import with_presentation

    assert with_presentation(None, ["tms_task_flat"]) is None
    assert with_presentation("not a dict", None) == "not a dict"


def test_an_error_result_still_gets_a_consistent_shape():
    """An error result carries no columns. The two fields must still be
    present and agree, or the frontend has to special-case it."""
    from pipeline.labels import with_presentation

    out = with_presentation({"error": "boom", "sqlstate": "42P01"},
                            ["tms_business_object_flat"])
    assert out["column_order"] == []
    assert out["hidden_columns"] == []
    assert out["error"] == "boom"


def test_the_presentation_fields_survive_debug_being_off():
    """Debug off is the mode the grid runs in.

    pipeline.redact.public_response is a whitelist, so a field added to the
    response is dropped until someone puts it there on purpose. These two are
    lists of integer positions -- they name no column, table or query -- so
    they are safe to expose, and useless if they are not.
    """
    from pipeline.redact import public_response

    full = {
        "question": "Show the AR_YD_Suiting items",
        "generated_sql": "SELECT ... -- must not survive",
        "result": {
            "columns": ["business_object_note", "business_object_id"],
            "column_labels": ["Business Object Note", "Business Object Id"],
            "rows": [["n", 1]],
            "row_count": 1,
            "truncated": False,
            "column_order": [1, 0],
            "hidden_columns": [0],
        },
    }
    public = public_response(full)

    assert public["result"]["column_order"] == [1, 0]
    assert public["result"]["hidden_columns"] == [0]
    # The guarantees that were already here must not have been widened.
    assert "columns" not in public["result"], "raw column names leaked"
    assert "generated_sql" not in public, "SQL leaked"
