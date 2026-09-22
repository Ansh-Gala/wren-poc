"""Which columns matter, for a result whose columns the user did not choose.

Everything here is positional. A result may project the same name twice --
COUNT(*) twice, or a join taking initiative_ref_id from both sides -- and
the frontend keys its rows by position for exactly that reason, so a
name-based answer would have to be re-resolved by the caller and would be
wrong in the one case that matters.
"""

from __future__ import annotations

from pipeline.column_order import presentation


def test_named_columns_lead_in_the_order_the_file_gives_them():
    columns = ["business_unit", "initiative_status", "initiative_id"]
    out = presentation(columns, ["tms_initiative_flat"])
    # File order, not result order: id, then status, then unit.
    assert [columns[i] for i in out["order"]] == [
        "initiative_id", "initiative_status", "business_unit"]


def test_unlisted_columns_keep_their_own_order_after_the_named_ones():
    """A generated alias has never appeared in any registry and still has to
    be shown somewhere predictable."""
    columns = ["avg_delay_days", "initiative_id", "some_new_column"]
    out = presentation(columns, ["tms_initiative_flat"])
    assert [columns[i] for i in out["order"]] == [
        "initiative_id", "avg_delay_days", "some_new_column"]


def test_hidden_columns_are_positions_and_stay_inside_the_order():
    """Hidden is a display hint, not a deletion.

    The column is still in the result, still in `order`, and still exported --
    the frontend starts it collapsed. Dropping it from `order` would make the
    two lists disagree about how many columns there are.
    """
    columns = ["initiative_id", "initiative_note"]
    out = presentation(columns, ["tms_initiative_flat"])
    assert out["hidden"] == [1]
    assert sorted(out["order"]) == [0, 1]


def test_a_duplicated_column_name_gets_both_of_its_positions():
    columns = ["initiative_id", "initiative_id"]
    out = presentation(columns, ["tms_initiative_flat"])
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
    columns = ["initiative_id", "workflow_id", "avg_delay_days",
               "initiative_status", "initiative_status"]
    out = presentation(columns, ["tms_initiative_flat"])
    assert sorted(out["order"]) == list(range(len(columns)))
    assert all(0 <= i < len(columns) for i in out["hidden"])


def test_the_first_configured_table_decides_for_a_join():
    """Not merged: a join's columns come from two tables, and merging their
    priority lists would invent an order neither file states."""
    columns = ["task_id", "initiative_id"]
    out = presentation(columns, ["tms_task_flat", "tms_initiative_flat"])
    assert [columns[i] for i in out["order"]] == ["task_id", "initiative_id"]


def test_labels_attaches_presentation_without_disturbing_anything():
    from pipeline.labels import with_presentation

    result = {"columns": ["initiative_note", "initiative_id"],
              "rows": [["n", 1]], "row_count": 1, "truncated": False}
    out = with_presentation(result, ["tms_initiative_flat"])

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
                            ["tms_initiative_flat"])
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
            "columns": ["initiative_note", "initiative_id"],
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


# --- Guards on metadata/column_hierarchy.yaml itself -------------------------
#
# The file is a plain list of names with no schema behind it, and it exists in
# two copies. Both of its failure modes are silent: a name that is not a real
# column does nothing, and an edit to one copy leaves the other behind. Neither
# shows up in presentation() output, so neither shows up in the parity harness.

import os
from pathlib import Path

import pytest
import yaml

_ROOT = Path(__file__).resolve().parents[1]
_HIERARCHY = _ROOT / "metadata" / "column_hierarchy.yaml"


def _module_metadata() -> Path | None:
    """The PHP port's copy of metadata/, or None if the module is not here.

    The Python project has to stay standalone -- it is the specification, and
    it is cloned on machines that carry no Drupal -- so a missing module skips
    rather than fails.
    """
    env = os.environ.get("VF_MODULE_ROOT")
    candidates = [Path(env)] if env else []
    candidates.append(Path("C:/xampp/htdocs/dev-arvind-retail-chatbot/web"
                           "/modules/custom/vf_sql_chatbot"))
    for root in candidates:
        if (root / "metadata" / "column_hierarchy.yaml").is_file():
            return root / "metadata"
    return None


def test_every_column_the_hierarchy_names_is_a_column_that_exists():
    """An unknown name is not an error to the loader, so it has to be one here.

    This is how a typo becomes a no-op: `presentation` looks the name up in a
    rank map, misses, and treats the column as unlisted. The file reads as
    though it configured something and configures nothing. Caught once already
    -- tms_initiative_attributes_flat listed initiative_ref_id, a
    column that table does not have.
    """
    schema = yaml.safe_load(
        (_ROOT / "metadata" / "schema_description.yaml").read_text(encoding="utf-8"))
    cfg = yaml.safe_load(_HIERARCHY.read_text(encoding="utf-8")) or {}

    unknown = []
    for table, spec in (cfg.get("tables") or {}).items():
        real = set((((schema.get("tables") or {}).get(table)) or {}).get("columns") or {})
        if not real:
            unknown.append(f"{table} (no such table)")
            continue
        for key in ("priority", "hidden"):
            unknown += [f"{table}.{col} (in {key})"
                        for col in (spec.get(key) or []) if col not in real]

    assert not unknown, "column_hierarchy.yaml names things that do not exist: " \
                        + ", ".join(unknown)


def test_the_two_copies_of_the_hierarchy_are_byte_identical():
    """The port reads its own copy of this file.

    Byte-identical rather than semantically equal, because line endings are one
    of the ways it has drifted -- and because the two copies exist only so that
    each project can be checked out alone, never so they can disagree.
    """
    module_metadata = _module_metadata()
    if module_metadata is None:
        pytest.skip("PHP module not present; set VF_MODULE_ROOT to check parity")

    theirs = module_metadata / "column_hierarchy.yaml"
    assert _HIERARCHY.read_bytes() == theirs.read_bytes(), (
        f"{_HIERARCHY} and {theirs} have drifted; re-sync them in one commit")


# --- Grouping nomination ----------------------------------------------------

def test_a_nominated_group_and_its_aggregates_come_back_as_positions():
    from pipeline.column_order import grouping

    columns = ["initiative_type", "open_task_count", "total_task_count",
               "business_unit"]
    out = grouping(columns, ["tms_initiative_flat"], True)
    assert out["row_groups"] == [0]
    assert out["value_columns"] == [{"index": 1, "aggFunc": "sum"},
                                    {"index": 2, "aggFunc": "sum"}]


def test_a_table_nomination_alone_no_longer_groups_anything():
    """The model decides whether THIS answer reads better grouped.

    The file says which columns may head a group; it cannot say whether the
    question wanted one, and on its own it fired on every answer off a
    nominated table -- which is how answers nobody asked to have grouped came
    back grouped anyway.
    """
    from pipeline.column_order import grouping

    columns = ["initiative_type", "open_task_count"]
    assert grouping(columns, ["tms_initiative_flat"])["row_groups"] == []
    assert grouping(columns, ["tms_initiative_flat"], False)["row_groups"] == []
    assert grouping(columns, ["tms_initiative_flat"], True)["row_groups"] == [0]


def test_pivot_is_not_nominated_anywhere_yet():
    """Grouping shipped without it deliberately.

    Pivot is the half that breaks the layout: pagination counts top-level
    groups, so with pivotMode and no row groups the pager reads "1 to 1 of 1".
    """
    from pipeline.column_order import grouping

    for table in ("tms_initiative_flat", "tms_task_flat"):
        assert grouping(["initiative_type", "task_department"],
                        [table], True)["pivot_columns"] == []


def test_a_table_that_nominates_nothing_is_never_grouped():
    """The default. Grouping changes what a row means, so it is opt-in."""
    from pipeline.column_order import grouping

    out = grouping(["user_id", "user_name"], ["tms_user_flat"], True)
    assert out == {"row_groups": [], "pivot_columns": [], "value_columns": []}


def test_a_nomination_the_result_did_not_project_is_simply_absent():
    """The nomination is per table; the result is per question."""
    from pipeline.column_order import grouping

    out = grouping(["initiative_id", "initiative_status"],
                   ["tms_initiative_flat"], True)
    assert out["row_groups"] == []
    assert out["value_columns"] == []


def test_an_unknown_aggfunc_is_dropped_rather_than_passed_through():
    """ag-grid renders an unknown aggFunc as a blank column and says nothing,
    which is the same silent failure an unknown column name has in this
    file -- so it is rejected here instead."""
    import pipeline.column_order as co

    spec = {"value_columns": [{"column": "open_task_count", "aggFunc": "median"},
                              {"column": "total_task_count", "aggFunc": "SUM"}]}
    original = co._spec
    co._spec = lambda tables: spec
    try:
        out = co.grouping(["open_task_count", "total_task_count"], ["anything"],
                          True)
    finally:
        co._spec = original

    # median is not one of the seven; SUM is, case-insensitively.
    assert out["value_columns"] == [{"index": 1, "aggFunc": "sum"}]


def test_no_columns_is_not_an_error_for_grouping_either():
    from pipeline.column_order import grouping

    assert grouping(None, ["tms_task_flat"], True) == {
        "row_groups": [], "pivot_columns": [], "value_columns": []}


def test_grouping_survives_debug_being_off():
    from pipeline.redact import public_response

    out = public_response({"result": {
        "rows": [["AR_YD_Suiting", 3]], "column_labels": ["Type", "Open"],
        "grouping": {"row_groups": [0], "pivot_columns": [],
                     "value_columns": [{"index": 1, "aggFunc": "sum"}]},
    }})
    assert out["result"]["grouping"]["row_groups"] == [0]


def test_every_nominated_column_exists_and_every_aggfunc_is_real():
    """The same guard priority and hidden get, for the same reason."""
    import yaml
    from pipeline.column_order import _AGG_FUNCS

    schema = yaml.safe_load(
        (_ROOT / "metadata" / "schema_description.yaml").read_text(encoding="utf-8"))
    cfg = yaml.safe_load(_HIERARCHY.read_text(encoding="utf-8")) or {}

    problems = []
    for table, spec in (cfg.get("tables") or {}).items():
        real = set((((schema.get("tables") or {}).get(table)) or {}).get("columns") or {})
        for column in (spec.get("row_groups") or []) + (spec.get("pivot_columns") or []):
            if column not in real:
                problems.append(f"{table}.{column} (nominated, does not exist)")
        for entry in (spec.get("value_columns") or []):
            if entry.get("column") not in real:
                problems.append(f"{table}.{entry.get('column')} (value, does not exist)")
            if str(entry.get("aggFunc") or "").lower() not in _AGG_FUNCS:
                problems.append(f"{table}.{entry.get('column')}: bad aggFunc "
                                f"{entry.get('aggFunc')!r}")
    assert not problems, "; ".join(problems)
