"""The follow-up layer: what the system says after, or instead of, an answer.

The contract these tests pin down is the one a frontend will render, so they
assert on structure rather than on phrasing. A label may be reworded; an
action's field and value may not.
"""

from __future__ import annotations


def _state_after(sql: str, question: str = "Show the AR_YD_Suiting items",
                 rows: int = 22):
    from pipeline.context import ConversationState, update_state
    state = ConversationState()
    update_state(state, question, sql, rows, "new_block")
    return state


def test_exploration_offers_next_moves_grounded_in_the_schema():
    from pipeline.followup import explore

    state = _state_after(
        "SELECT initiative_id, initiative_status "
        "FROM tms_initiative_flat WHERE initiative_type = 'AR_YD_Suiting'"
    )
    followup = explore(state, row_count=22)

    assert followup is not None
    assert followup.type == "exploration"
    assert 2 <= len(followup.suggestions) <= 4, "2-4 suggestions, per the brief"

    for suggestion in followup.suggestions:
        assert suggestion.action.type in {
            "add_filter", "add_group_by", "set_sort", "set_limit",
            "remove_filter", "set_aggregate", "drill_down",
        }
        assert suggestion.id and suggestion.label


def test_applying_a_filter_suggestion_narrows_the_state_and_asks_for_it():
    """A suggestion becomes a state change plus a question, never SQL.

    Keeping SQL out of the action is the point: the model remains the only
    thing that writes queries, so a suggestion cannot drift away from what the
    pipeline would otherwise produce.
    """
    from pipeline.followup import Action, apply_action

    state = _state_after(
        "SELECT initiative_id FROM tms_initiative_flat "
        "WHERE initiative_type = 'AR_YD_Suiting'"
    )
    question = apply_action(
        state, Action("add_filter", "initiative_status", "=", "Active"))

    assert "initiative_status" in state.active_filters
    assert "Active" in state.active_filters["initiative_status"]
    assert "Active" in question
    assert "SELECT" not in question.upper()


def test_a_clarification_naming_a_known_column_offers_that_column_real_values(listed_values):
    """The model says which column it could not satisfy; we supply the values.

    Splitting it this way is what keeps candidates honest. The model is good
    at noticing that "Breached" is not a thing and bad at reciting the four
    values that are; the schema is the reverse. Asked for SLA status
    "Breached", the useful reply names Delayed and On Time, and neither may be
    invented.
    """
    from pipeline.followup import clarification_followup

    followup = clarification_followup(
        "There is no 'Breached' value. task_sla_status only takes two values."
    )

    assert followup.type == "clarification"
    assert followup.reason == "unknown_value"
    assert {s.action.value for s in followup.suggestions} == {"Delayed", "On Time"}
    assert all(s.action.field == "task_sla_status" for s in followup.suggestions)


def test_an_open_ended_clarification_offers_nothing_and_invites_free_text():
    """No column named means no candidates exist. Inventing some would be worse."""
    from pipeline.followup import clarification_followup

    followup = clarification_followup(
        "Could you say which items you mean? The question is too broad to answer."
    )

    assert followup.type == "clarification"
    assert followup.suggestions == []
    assert followup.allow_free_text is True


def test_suggestions_do_not_spend_every_slot_on_one_column():
    """Four buttons should offer four choices, not one choice four ways.

    The registry names three status rules -- active, closed, short closed --
    and taking them all filled three of the four slots with values of the same
    column, pushing out sorting and counting entirely. A user who wants a
    different status can say so; what they cannot do is discover an option
    that was never shown.
    """
    from pipeline.followup import explore

    state = _state_after(
        "SELECT initiative_id FROM tms_initiative_flat "
        "WHERE initiative_type = 'AR_YD_Suiting'"
    )
    followup = explore(state, row_count=22)

    fields = [s.action.field for s in followup.suggestions]
    assert len(fields) == len(set(fields)), f"repeated field in {fields}"


def test_the_wire_format_carries_everything_a_frontend_needs():
    """A guard on the contract, not a test of new behaviour.

    The frontend is written against these keys, so a rename here is a broken
    UI somewhere else. The point of the shape is that nothing has to be read
    as prose: the label is for a person, the action is for the code, and the
    two are separate fields.
    """
    from pipeline.followup import Action, FollowUp, Suggestion

    payload = FollowUp(
        type="exploration",
        reason="useful_next_actions",
        question="What would you like to explore next?",
        suggestions=[Suggestion(
            id="filter_active",
            label="Only the active ones",
            action=Action("add_filter", "initiative_status", "=", "Active"),
        )],
    ).to_dict()

    assert set(payload) == {
        "follow_up_required", "type", "reason", "question",
        "suggestions", "allow_free_text",
    }
    assert payload["follow_up_required"] is True

    suggestion = payload["suggestions"][0]
    assert set(suggestion) == {"id", "label", "action"}
    assert suggestion["action"] == {
        "type": "add_filter", "field": "initiative_status",
        "operator": "=", "value": "Active",
    }


def test_an_unknown_action_type_is_refused_at_construction():
    """The contract is only stable if it cannot be widened by accident."""
    import pytest

    from pipeline.followup import Action

    with pytest.raises(ValueError):
        Action("do_something_clever", "status")


def test_a_single_filter_can_still_be_dropped(listed_values):
    """"Show all again" is a next move even when only one thing is narrowing.

    Requiring two filters before offering to remove one left "How many items
    are active?" with a single suggestion, which is not a choice, so the layer
    said nothing at all. The subject is still never offered for removal --
    dropping that is not a refinement, it is a different question.
    """
    from pipeline.followup import explore

    state = _state_after(
        "SELECT COUNT(*) FROM tms_initiative_flat "
        "WHERE initiative_status = 'Active'",
        question="How many items are active?", rows=258,
    )
    followup = explore(state, row_count=1)

    assert followup is not None, "offered nothing at all"
    assert any(s.action.type == "remove_filter"
               and s.action.field == "initiative_status"
               for s in followup.suggestions)


def test_the_subject_itself_is_never_offered_for_removal():
    """Dropping the subject is not a refinement of the question."""
    from pipeline.followup import explore

    state = _state_after(
        "SELECT initiative_id FROM tms_initiative_flat "
        "WHERE initiative_type = 'AR_YD_Suiting'"
    )
    followup = explore(state, row_count=22)
    assert not any(s.action.type == "remove_filter" for s in followup.suggestions)


def _which_ar_yd():
    """A pending "which AR_YD type?" question, as the model can ask it."""
    from pipeline.followup import Action, FollowUp, Suggestion

    return FollowUp(
        type="clarification",
        reason="unknown_value",
        question="Which AR_YD type did you mean?",
        suggestions=[
            Suggestion(id=f"filter_initiative_type_{value}", label=value,
                       action=Action(type="add_filter", field="initiative_type",
                                     operator="=", value=value))
            for value in ("AR_YD_SHIRTING", "AR_YD_Shirting", "AR_YD_Suiting")
        ],
    )


def test_answering_a_clarification_resumes_the_original_question():
    """Asking "which one?" is only useful if the answer means something.

    The system asked which AR_YD type was meant and the user replied
    "AR_YD_Suiting". With no memory of the question that prompted it, that
    reply reached the model as a bare noun with empty context, and the model
    -- reasonably -- asked what to do with it. The thread deadlocked one turn
    after the clarification that was supposed to unblock it.
    """
    from pipeline.followup import resolve_clarification

    original = "Show the AR_YD items"
    pending = _which_ar_yd()

    assert resolve_clarification("AR_YD_Suiting", original, pending) == \
        "Show the AR_YD_Suiting items"


def test_a_clarification_can_be_answered_with_the_suggestion_id():
    """A frontend sends the id it was given, not the label a person read."""
    from pipeline.followup import resolve_clarification

    original = "Show the AR_YD items"
    pending = _which_ar_yd()
    chosen = next(s for s in pending.suggestions
                  if s.action.value == "AR_YD_Shirting")

    assert resolve_clarification(chosen.id, original, pending) == \
        "Show the AR_YD_Shirting items"


def test_an_unrelated_reply_is_not_treated_as_an_answer():
    """The user is allowed to ignore the question and ask something else."""
    from pipeline.followup import resolve_clarification

    original = "Show the AR_YD items"
    pending = _which_ar_yd()

    assert resolve_clarification("how many tasks are open?", original, pending) is None


def test_the_column_can_be_named_in_its_own_key_instead_of_the_question(listed_values):
    """A question written for a person still gets the real values as chips.

    The scan of the prose could only find a column the question named out
    loud, so offering chips and writing a clean question were in conflict.
    `about` carries the column separately, and is never shown.
    """
    from pipeline.followup import clarification_followup

    followup = clarification_followup(
        "Was that on time, or running late?",
        about="task_sla_status",
    )

    assert followup.reason == "unknown_value"
    assert {s.action.value for s in followup.suggestions} == {"Delayed", "On Time"}


def test_the_question_is_still_scanned_when_no_column_is_named(listed_values):
    """Replies that predate the key, and replies that omit it, still work."""
    from pipeline.followup import clarification_followup

    followup = clarification_followup(
        "There is no 'Breached' value. task_sla_status only takes two values."
    )

    assert followup.reason == "unknown_value"


def test_a_column_that_is_not_a_column_offers_nothing_rather_than_guessing():
    from pipeline.followup import clarification_followup

    followup = clarification_followup(
        "Which one did you mean?", about="not_a_real_column"
    )

    assert followup.reason == "ambiguous_request"
    assert followup.suggestions == []
