"""The word the UI uses for a Business Object.

The database calls it a business object and always will -- every table, column
and foreign key says so, and renaming any of them would be a migration. The
people reading the grid call it an Initiative. This is the seam between the
two, and it holds in exactly one direction: nothing here may reach the model
or the query.

The trap that makes this a phrase substitution rather than a word one is
`business_unit`. A per-word map turning "business" into "initiative" reads
plausibly until it renames the Business Unit column, which is a different
thing entirely and is not being renamed.
"""

from __future__ import annotations

import pytest

from pipeline.labels import column_label, column_phrase


@pytest.mark.parametrize("name,heading", [
    ("initiative_id", "Initiative Id"),
    ("initiative_ref_id", "Initiative Ref Id"),
    ("initiative_status", "Initiative Status"),
    ("initiative_type", "Initiative Type"),
    ("initiative_color", "Initiative Color"),
    ("initiative_note", "Initiative Note"),
    ("initiative_created_at", "Initiative Created At"),
    ("initiative_updated_at", "Initiative Updated At"),
    ("initiative_client_due_at", "Initiative Client Due At"),
    # Generated aliases, which no registry has ever seen.
    ("initiative_count", "Initiative Count"),
    ("is_initiative_delayed", "Is Initiative Delayed"),
    # The only column with a bare `bo` segment.
    ("bo_id", "Initiative Id"),
])
def test_a_reader_sees_initiative(name, heading):
    assert column_label(name) == heading


@pytest.mark.parametrize("name,heading", [
    # The whole reason this is a phrase pass: "business" alone is not the term.
    ("business_unit", "Business Unit"),
    ("business_unit_count", "Business Unit Count"),
])
def test_business_unit_is_a_different_thing_and_keeps_its_name(name, heading):
    assert column_label(name) == heading


@pytest.mark.parametrize("name,phrase", [
    ("initiative_status", "initiative status"),
    ("initiative_type", "initiative type"),
    ("business_unit", "business unit"),
])
def test_the_sentence_form_says_the_same_word_as_the_heading(name, phrase):
    """The chips are built from column names too.

    "Group by business object status" under a column headed "Initiative
    Status" is the same drift as two copies of a metadata file, only visible.
    """
    assert column_phrase(name) == phrase


def test_the_chips_say_initiative():
    """Through the follow-up layer itself, not just the helper."""
    from pipeline.followup import Action, apply_action
    from pipeline.context import ConversationState

    state = ConversationState()
    assert apply_action(state, Action(type="add_group_by",
                                      field="initiative_status")) \
        == "Group them by initiative status"
    assert apply_action(state, Action(type="remove_filter",
                                      field="initiative_status")) \
        == "Remove the initiative status filter"


def test_no_column_name_is_altered_on_the_way_to_the_database():
    """Presentation only. `columns` is what PostgreSQL said, and stays so."""
    from pipeline.labels import with_column_labels

    result = {"columns": ["initiative_id", "business_unit"],
              "rows": [[1, "Shirting"]]}
    out = with_column_labels(result)
    assert out["columns"] == ["initiative_id", "business_unit"]
    assert out["column_labels"] == ["Initiative Id", "Business Unit"]


def test_the_error_messages_a_person_reads_say_initiative():
    from pipeline.redact import safe_error

    for sqlstate in ("42703", "42P01"):
        message = safe_error("relation \"tms_nope\" does not exist", sqlstate)
        assert "initiatives" in message
        assert "business object" not in message.lower()
