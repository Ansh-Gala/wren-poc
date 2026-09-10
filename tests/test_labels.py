"""Column headings: readable in the UI, untouched in the query."""

from __future__ import annotations

import pytest

from pipeline.labels import column_label, column_labels


@pytest.mark.parametrize("name,expected", [
    ("task_name", "Task Name"),
    ("task_start_at", "Task Start At"),
    ("business_object_ref_id", "Initiative Ref Id"),
])
def test_the_stated_cases(name, expected):
    assert column_label(name) == expected


@pytest.mark.parametrize("name,expected", [
    ("business_object_client_due_at", "Initiative Client Due At"),
    # One word.
    ("count", "Count"),
    ("role", "Role"),
    # Digits stay where they are; they are part of the name, not decoration.
    ("field_1", "Field 1"),
    ("field_2", "Field 2"),
    ("buff_penetration_prcnt", "Buff Penetration Prcnt"),
    # Runs of underscores, and leading or trailing ones, produce no blank words.
    ("task__display___name", "Task Display Name"),
    ("_task_name", "Task Name"),
    ("task_name_", "Task Name"),
    # A generated alias, which no registry has ever seen. This is why the
    # transformation has to be a rule rather than a lookup table.
    ("avg_delay_days", "Avg Delay Days"),
    ("business_object_count", "Initiative Count"),
    # Already-readable input is left readable rather than mangled.
    ("Total Tasks", "Total Tasks"),
])
def test_ordinary_names(name, expected):
    assert column_label(name) == expected


@pytest.mark.parametrize("name,expected", [
    ("task_sla_status", "Task SLA Status"),
    ("task_sla_hours", "Task SLA Hours"),
    ("bo_id", "Initiative Id"),
    ("moq", "MOQ"),
    ("csbd_date", "CSBD Date"),
    ("pi_date", "PI Date"),
    ("mcode_won_number", "Mcode WON Number"),
])
def test_acronyms_the_schema_itself_capitalises(name, expected):
    """Only where title case would be wrong. "Task Sla Status" reads as a typo."""
    assert column_label(name) == expected


@pytest.mark.parametrize("name", ["", None, "   ", "_", "___"])
def test_nothing_in_gives_nothing_out(name):
    """A heading is never None, because the UI writes it into a cell."""
    assert column_label(name) == ""


def test_labels_align_positionally_with_the_columns_they_describe():
    """The UI zips these against the column list, so length and order matter."""
    columns = ["task_id", "", "task_sla_status", "field_1"]
    assert column_labels(columns) == ["Task Id", "", "Task SLA Status", "Field 1"]
    assert len(column_labels(columns)) == len(columns)


def test_an_absent_column_list_is_not_an_error():
    assert column_labels(None) == []
    assert column_labels([]) == []


def test_a_wide_result_is_labelled_in_full():
    """120 columns is the real ceiling here: the widest view has that many."""
    columns = [f"column_number_{i}" for i in range(120)]
    labels = column_labels(columns)
    assert len(labels) == 120
    assert labels[0] == "Column Number 0"
    assert labels[119] == "Column Number 119"


def test_the_database_column_names_are_never_modified():
    """The whole point: labels are additional, not a replacement.

    A caller that mutated its input would change what the next turn's state
    reader and the debug pane report, and the SQL would then disagree with the
    console.
    """
    columns = ["task_name", "task_sla_status", "bo_id"]
    original = list(columns)
    column_labels(columns)
    assert columns == original


def test_every_real_column_in_the_schema_gets_a_non_empty_label():
    """No column in this database renders as a blank heading."""
    import pathlib

    import yaml

    doc = yaml.safe_load(
        (pathlib.Path(__file__).resolve().parents[1]
         / "metadata" / "schema_description.yaml").read_text(encoding="utf-8")
    )
    names = [
        column
        for spec in (doc.get("tables") or {}).values()
        for column in (spec.get("columns") or {})
    ]
    assert len(names) > 100, "expected the full schema"
    blank = [n for n in names if not column_label(n)]
    assert not blank, f"columns with no label: {blank}"


# --------------------------------------------- results, as the API sends them --

def test_a_result_gains_labels_without_losing_its_column_names():
    """Both travel. Debug strips `columns` later; that is not this layer's job."""
    from pipeline.labels import with_column_labels

    result = {"columns": ["task_id", "task_sla_status"], "rows": [[1, "Delayed"]],
              "row_count": 1, "truncated": False}
    out = with_column_labels(result)

    assert out["columns"] == ["task_id", "task_sla_status"]
    assert out["column_labels"] == ["Task Id", "Task SLA Status"]
    assert out["rows"] == [[1, "Delayed"]]
    assert out["row_count"] == 1


def test_labels_are_always_present_when_columns_are():
    """The console falls back to raw column names when labels are absent.

    That fallback is why a stale server showed task_id, task_display_name and
    business_object_ref_id as headings: the page was current, the process was
    not. So the invariant worth asserting is that a result carrying columns
    always carries labels of the same length.
    """
    from pipeline.labels import with_column_labels

    for columns in ([], ["count"], ["a", "b", "c"], ["" , "x"]):
        out = with_column_labels({"columns": columns, "rows": []})
        assert "column_labels" in out
        assert len(out["column_labels"]) == len(columns)


def test_a_result_with_no_columns_key_still_gets_the_field():
    from pipeline.labels import with_column_labels

    assert with_column_labels({"rows": []})["column_labels"] == []


def test_a_missing_result_passes_through_untouched():
    """A clarification has no rows, and must not grow an empty table."""
    from pipeline.labels import with_column_labels

    assert with_column_labels(None) is None
    assert with_column_labels("not a dict") == "not a dict"


def test_the_original_result_is_not_mutated():
    from pipeline.labels import with_column_labels

    result = {"columns": ["task_id"], "rows": [[1]]}
    with_column_labels(result)
    assert "column_labels" not in result
