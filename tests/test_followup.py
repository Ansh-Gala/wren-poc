"""The follow-up layer: what the system says after, or instead of, an answer.

The contract these tests pin down is the one a frontend will render, so they
assert on structure rather than on phrasing. A label may be reworded; an
action's field and value may not.
"""

from __future__ import annotations

from benchmark.followup import clarify_entity
from benchmark.lean_runner import load_gazetteer


def test_partial_entity_name_asks_which_one_and_offers_only_real_values():
    """"AR_YD" names three business object types, so the system must ask.

    The candidates come from the gazetteer, which is generated from the
    database. Nothing here may be invented: offering a plausible-looking type
    that does not exist is worse than asking an open question.
    """
    gazetteer = load_gazetteer()
    followup = clarify_entity("Show the AR_YD items", gazetteer)

    assert followup is not None
    assert followup.type == "clarification"
    assert followup.reason == "ambiguous_entity"

    offered = [s.action.value for s in followup.suggestions]
    assert "AR_YD_Suiting" in offered
    assert "AR_YD_Shirting" in offered
    assert set(offered) <= set(gazetteer), "offered a value the database does not have"


def _state_after(sql: str, question: str = "Show the AR_YD_Suiting items",
                 rows: int = 22):
    from benchmark.context import ConversationState, update_state
    state = ConversationState()
    update_state(state, question, sql, rows, "AR_YD_Suiting", "new_block")
    return state


def test_exploration_offers_next_moves_grounded_in_the_schema():
    from benchmark.followup import explore

    state = _state_after(
        "SELECT business_object_id, business_object_status "
        "FROM tms_business_object_flat WHERE business_object_type = 'AR_YD_Suiting'"
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
    from benchmark.followup import Action, apply_action

    state = _state_after(
        "SELECT business_object_id FROM tms_business_object_flat "
        "WHERE business_object_type = 'AR_YD_Suiting'"
    )
    question = apply_action(
        state, Action("add_filter", "business_object_status", "=", "Active"))

    assert "business_object_status" in state.active_filters
    assert "Active" in state.active_filters["business_object_status"]
    assert "Active" in question
    assert "SELECT" not in question.upper()


def test_a_clarification_naming_a_known_column_offers_that_column_real_values():
    """The model says which column it could not satisfy; we supply the values.

    Splitting it this way is what keeps candidates honest. The model is good
    at noticing that "Breached" is not a thing and bad at reciting the four
    values that are; the schema is the reverse. Asked for SLA status
    "Breached", the useful reply names Delayed and On Time, and neither may be
    invented.
    """
    from benchmark.followup import clarification_followup

    followup = clarification_followup(
        "There is no 'Breached' value. task_sla_status only takes two values."
    )

    assert followup.type == "clarification"
    assert followup.reason == "unknown_value"
    assert {s.action.value for s in followup.suggestions} == {"Delayed", "On Time"}
    assert all(s.action.field == "task_sla_status" for s in followup.suggestions)


def test_an_open_ended_clarification_offers_nothing_and_invites_free_text():
    """No column named means no candidates exist. Inventing some would be worse."""
    from benchmark.followup import clarification_followup

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
    from benchmark.followup import explore

    state = _state_after(
        "SELECT business_object_id FROM tms_business_object_flat "
        "WHERE business_object_type = 'AR_YD_Suiting'"
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
    from benchmark.followup import Action, FollowUp, Suggestion

    payload = FollowUp(
        type="exploration",
        reason="useful_next_actions",
        question="What would you like to explore next?",
        suggestions=[Suggestion(
            id="filter_active",
            label="Only the active ones",
            action=Action("add_filter", "business_object_status", "=", "Active"),
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
        "type": "add_filter", "field": "business_object_status",
        "operator": "=", "value": "Active",
    }


def test_an_unknown_action_type_is_refused_at_construction():
    """The contract is only stable if it cannot be widened by accident."""
    import pytest

    from benchmark.followup import Action

    with pytest.raises(ValueError):
        Action("do_something_clever", "status")


def test_a_single_filter_can_still_be_dropped():
    """"Show all again" is a next move even when only one thing is narrowing.

    Requiring two filters before offering to remove one left "How many items
    are active?" with a single suggestion, which is not a choice, so the layer
    said nothing at all. The subject is still never offered for removal --
    dropping that is not a refinement, it is a different question.
    """
    from benchmark.followup import explore

    state = _state_after(
        "SELECT COUNT(*) FROM tms_business_object_flat "
        "WHERE business_object_status = 'Active'",
        question="How many items are active?", rows=258,
    )
    followup = explore(state, row_count=1)

    assert followup is not None, "offered nothing at all"
    assert any(s.action.type == "remove_filter"
               and s.action.field == "business_object_status"
               for s in followup.suggestions)


def test_the_subject_itself_is_never_offered_for_removal():
    """Dropping the subject is not a refinement of the question."""
    from benchmark.followup import explore

    state = _state_after(
        "SELECT business_object_id FROM tms_business_object_flat "
        "WHERE business_object_type = 'AR_YD_Suiting'"
    )
    followup = explore(state, row_count=22)
    assert not any(s.action.type == "remove_filter" for s in followup.suggestions)


def test_a_word_inside_an_entity_name_is_not_a_partial_entity_name():
    """"the sales team" is a role. AR_SALESPLAN_Suiting is not what was meant.

    Matching any substring made "sales" a candidate prefix for three business
    object types, so a perfectly clear question about task assignment was
    answered with "which sales type did you mean?" and never ran. A partial
    name has to break on the underscores the names are built from.
    """
    from benchmark.followup import clarify_entity

    gazetteer = load_gazetteer()
    assert clarify_entity("Show the tasks assigned to the sales team", gazetteer) is None
    # The genuinely truncated names must still be caught.
    assert clarify_entity("Show the AR_YD items", gazetteer) is not None
    assert clarify_entity("Show the SALESPLAN items", gazetteer) is not None


def test_a_trailing_category_word_is_a_category_not_a_truncated_name():
    """"suiting items" means all of them, not one of them.

    Suiting is the last component of all five types that carry it, so it names
    a family rather than an unfinished identifier. AR_YD is the last component
    of none of its matches, which is what makes it a name the user stopped
    typing.
    """
    from benchmark.followup import clarify_entity

    gazetteer = load_gazetteer()
    assert clarify_entity("how many suiting items are active?", gazetteer) is None
    assert clarify_entity("show the shirting items", gazetteer) is None
    assert clarify_entity("Show AR_PD items", gazetteer) is not None


def test_answering_a_clarification_resumes_the_original_question():
    """Asking "which one?" is only useful if the answer means something.

    The system asked which AR_YD type was meant and the user replied
    "AR_YD_Suiting". With no memory of the question that prompted it, that
    reply reached the model as a bare noun with empty context, and the model
    -- reasonably -- asked what to do with it. The thread deadlocked one turn
    after the clarification that was supposed to unblock it.
    """
    from benchmark.followup import clarify_entity, resolve_clarification

    original = "Show the AR_YD items"
    pending = clarify_entity(original, load_gazetteer())

    assert resolve_clarification("AR_YD_Suiting", original, pending) == \
        "Show the AR_YD_Suiting items"


def test_a_clarification_can_be_answered_with_the_suggestion_id():
    """A frontend sends the id it was given, not the label a person read."""
    from benchmark.followup import clarify_entity, resolve_clarification

    original = "Show the AR_YD items"
    pending = clarify_entity(original, load_gazetteer())
    chosen = next(s for s in pending.suggestions
                  if s.action.value == "AR_YD_Shirting")

    assert resolve_clarification(chosen.id, original, pending) == \
        "Show the AR_YD_Shirting items"


def test_an_unrelated_reply_is_not_treated_as_an_answer():
    """The user is allowed to ignore the question and ask something else."""
    from benchmark.followup import clarify_entity, resolve_clarification

    original = "Show the AR_YD items"
    pending = clarify_entity(original, load_gazetteer())

    assert resolve_clarification("how many tasks are open?", original, pending) is None


def test_suggestion_ids_are_unique_within_a_follow_up():
    """The id is the frontend's handle on a choice. Two choices cannot share one.

    business_object_type contains case-variant near-duplicates that are
    genuinely distinct values -- AR_YD_Shirting and AR_YD_SHIRTING, 52 rows
    and 2 rows. Lowercasing the value to build the id collapsed them, so a
    frontend sending back the id it was given would silently select the other
    one.
    """
    from benchmark.followup import clarify_entity

    followup = clarify_entity("Show the AR_YD items", load_gazetteer())
    ids = [s.id for s in followup.suggestions]
    assert len(ids) == len(set(ids)), f"duplicate suggestion id in {ids}"
