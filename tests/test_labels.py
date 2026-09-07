"""Column headings: readable in the UI, untouched in the query."""

from __future__ import annotations

import pytest

from pipeline.labels import column_label, column_labels


@pytest.mark.parametrize("name,expected", [
    ("task_name", "Task Name"),
    ("task_start_at", "Task Start At"),
    ("business_object_ref_id", "Business Object Ref Id"),
])
def test_the_stated_cases(name, expected):
    assert column_label(name) == expected


@pytest.mark.parametrize("name,expected", [
    ("business_object_client_due_at", "Business Object Client Due At"),
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
    ("business_object_count", "Business Object Count"),
    # Already-readable input is left readable rather than mangled.
    ("Total Tasks", "Total Tasks"),
])
def test_ordinary_names(name, expected):
    assert column_label(name) == expected


@pytest.mark.parametrize("name,expected", [
    ("task_sla_status", "Task SLA Status"),
    ("task_sla_hours", "Task SLA Hours"),
    ("bo_id", "BO Id"),
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
