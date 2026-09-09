"""The follow-up suggestion contract (spec section 8).

Structure, not phrasing -- except where the phrasing is the behaviour: under
the active-first default the status filter in force was never typed by the
user, so how it is offered back to them is the feature.
"""

from __future__ import annotations

from pipeline.context import ConversationState, update_state
from pipeline.followup import explore


def _state_after(sql: str, rows: int = 5) -> ConversationState:
    state = ConversationState()
    update_state(state, "Show the AR_NPD_Shirting items", sql, rows,
                 "AR_NPD_Shirting", "new_block")
    return state


_DEFAULTED = (
    "SELECT business_object_id, business_object_status "
    "FROM tms_business_object_flat "
    "WHERE business_object_type = 'AR_NPD_Shirting' "
    "AND business_object_status = 'Active'"
)


def test_the_active_filter_is_not_offered_again_once_it_is_in_force():
    """The default already applied it. Offering it would be offering a no-op."""
    followup = explore(_state_after(_DEFAULTED), row_count=5)
    assert followup is not None
    values = [s.action.value for s in followup.suggestions
              if s.action.type == "add_filter"]
    assert "Active" not in values


def test_escaping_the_default_is_offered_as_seeing_every_status():
    """The user never typed this filter, so it cannot be described as theirs.

    The action is unchanged -- remove_filter on the status column is exactly
    right -- but the label has to read like the question a person would ask.
    """
    followup = explore(_state_after(_DEFAULTED), row_count=5)
    escape = [s for s in followup.suggestions
              if s.action.type == "remove_filter"
              and s.action.field == "business_object_status"]
    assert len(escape) == 1, "no way offered to see the other statuses"
    label = escape[0].label.lower()
    assert "remove" not in label, f"still described as removing a filter: {label!r}"
    assert "status" in label


def test_a_filter_the_user_did_state_is_still_offered_as_a_removal():
    """Only the defaults are relabelled.

    A filter the user asked for is theirs to remove, and calling that "show
    every business unit" would be putting words in their mouth.
    """
    followup = explore(_state_after(
        "SELECT business_object_id FROM tms_business_object_flat "
        "WHERE business_object_type = 'AR_NPD_Shirting' "
        "AND business_unit = 'unit1'"), row_count=3)
    removals = [s for s in followup.suggestions if s.action.type == "remove_filter"]
    assert removals
    assert any("remove" in s.label.lower() for s in removals)


def test_a_closed_status_the_user_asked_for_is_not_treated_as_a_default():
    """Closed is a status the default never adds, so it is the user's."""
    followup = explore(_state_after(
        "SELECT business_object_id FROM tms_business_object_flat "
        "WHERE business_object_type = 'AR_NPD_Shirting' "
        "AND business_object_status = 'Closed'"), row_count=5)
    escape = [s for s in followup.suggestions
              if s.action.field == "business_object_status"]
    assert all("remove" in s.label.lower() for s in escape)


def test_an_open_task_filter_is_also_recognised_as_the_default():
    """The default covers two entities, so the relabelling must too."""
    followup = explore(_state_after(
        "SELECT task_id, task_status FROM tms_task_flat "
        "WHERE business_object_type = 'AR_YD_Suiting' "
        "AND task_status = 'open'"), row_count=32)
    escape = [s for s in (followup.suggestions if followup else [])
              if s.action.type == "remove_filter" and s.action.field == "task_status"]
    assert len(escape) == 1
    assert "remove" not in escape[0].label.lower()


def test_every_suggestion_carries_a_valid_action():
    from pipeline.followup import ACTION_TYPES

    followup = explore(_state_after(_DEFAULTED), row_count=5)
    for s in followup.suggestions:
        assert s.action.type in ACTION_TYPES
        assert s.id and s.label


def test_an_empty_result_is_offered_nothing():
    """Nothing to narrow. Suggesting a narrowing anyway is how a helpful
    feature becomes noise."""
    assert explore(_state_after(_DEFAULTED), row_count=0) is None


def test_a_turn_that_never_ran_is_offered_nothing():
    assert explore(ConversationState(), row_count=None) is None
    assert explore(None, row_count=5) is None


def test_at_most_four_and_never_exactly_one():
    followup = explore(_state_after(_DEFAULTED), row_count=5)
    assert 2 <= len(followup.suggestions) <= 4


def test_the_wire_format_survives_having_no_suggestions():
    """Empty or missing suggestion data must not break the response."""
    from pipeline.followup import NO_FOLLOWUP

    wire = NO_FOLLOWUP.to_dict()
    assert wire["follow_up_required"] is False
    assert wire["suggestions"] == []
    assert set(wire) == {"follow_up_required", "type", "reason", "question",
                         "suggestions", "allow_free_text"}


def test_suggestion_ids_are_unique_within_a_turn():
    """The frontend keys its buttons by id."""
    followup = explore(_state_after(_DEFAULTED), row_count=5)
    ids = [s.id for s in followup.suggestions]
    assert len(ids) == len(set(ids))
