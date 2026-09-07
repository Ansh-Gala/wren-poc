"""Conversation state: reference resolution, topic switching, and bounded size."""

import pytest

from pipeline.context import (
    ConversationState, classify_turn, detect_entity, parse_sql_state,
    render_context, update_state,
)

GAZ = [
    "AR_YD_Suiting", "AR_NPD_Shirting", "AR_NPD_YD_SHIRTING",
    "AR_YD_Shirting", "AR_PD_Suiting", "AR_NPD_Suiting", "TESTING_MG", "test",
]

SQL_LIST = (
    "SELECT business_object_id, business_object_ref_id FROM tms_business_object_flat "
    "WHERE business_object_type = 'AR_YD_Suiting'"
)
SQL_ACTIVE = (
    "SELECT business_object_id FROM tms_business_object_flat "
    "WHERE business_object_type = 'AR_YD_Suiting' AND business_object_status = 'Active'"
)


def _state_after(question, sql, rows=22, gaz=GAZ, state=None):
    state = state or ConversationState()
    decision, entity = classify_turn(question, state, gaz)
    return update_state(state, question, sql, rows, entity, decision), decision


# ---------------------------------------------------------------- entity ----

def test_detect_entity_matches_exact_and_spaced_spellings():
    assert detect_entity("Show AR_YD_Suiting items", GAZ) == "AR_YD_Suiting"
    assert detect_entity("show the ar yd suiting ones", GAZ) == "AR_YD_Suiting"


def test_detect_entity_does_not_fire_on_substrings():
    """'test' is a real entity value; the word 'latest' must not match it."""
    assert detect_entity("show me the latest items", GAZ) is None
    assert detect_entity("contested greatest", GAZ) is None


def test_detect_entity_prefers_the_longest_match():
    assert detect_entity("Show AR_NPD_YD_SHIRTING items", GAZ) == "AR_NPD_YD_SHIRTING"


def test_detect_entity_returns_none_when_no_subject_is_named():
    assert detect_entity("only the active ones", GAZ) is None
    assert detect_entity("how many?", GAZ) is None


# ------------------------------------------------------------ classifying ----

def test_first_question_opens_a_block():
    assert classify_turn("Show AR_YD_Suiting items", ConversationState(), GAZ)[0] == "new_block"


def test_anaphora_continues_the_block():
    state, _ = _state_after("Show AR_YD_Suiting items", SQL_LIST)
    for q in ("only the active ones", "how many?", "group those by status",
              "sort them by status", "show me the first 5", "what about PVH?"):
        assert classify_turn(q, state, GAZ)[0] == "follow_up", q


def test_naming_a_different_entity_switches_subject():
    state, _ = _state_after("Show AR_YD_Suiting items", SQL_LIST)
    decision, entity = classify_turn("Show AR_NPD_Shirting items", state, GAZ)
    assert decision == "switch"
    assert entity == "AR_NPD_Shirting"


def test_naming_the_same_entity_is_still_a_follow_up():
    state, _ = _state_after("Show AR_YD_Suiting items", SQL_LIST)
    assert classify_turn("how many AR_YD_Suiting items are active?", state, GAZ)[0] == "follow_up"


def test_an_elliptical_subject_change_rebases_rather_than_resetting():
    """Regression: "What about X?" needs the previous question's shape.

    After "how many delayed tasks in AR_NPD_Suiting?", the question "What
    about AR_PD_Suiting?" means the same count for a different subject.
    Clearing the state left nothing to answer, and the system could only ask
    what was meant.
    """
    state, _ = _state_after(
        "Show delayed tasks in AR_NPD_Suiting",
        "SELECT task_id FROM tms_task_flat WHERE business_object_type = 'AR_NPD_Suiting' "
        "AND task_sla_status = 'Delayed'", 4)
    decision, entity = classify_turn("What about AR_PD_Suiting?", state, GAZ)
    assert decision == "rebase"
    assert entity == "AR_PD_Suiting"


def test_a_rebase_keeps_the_other_filters_but_drops_the_subject():
    state, _ = _state_after(
        "Show delayed tasks in AR_NPD_Suiting",
        "SELECT task_id FROM tms_task_flat WHERE business_object_type = 'AR_NPD_Suiting' "
        "AND task_sla_status = 'Delayed'", 4)
    decision, entity = classify_turn("What about AR_PD_Suiting?", state, GAZ)
    update_state(state, "What about AR_PD_Suiting?", None, None, entity, decision)
    assert state.active_entity == "AR_PD_Suiting"
    assert "AR_NPD_Suiting" not in str(state.active_filters)


def test_a_full_request_for_a_new_subject_still_switches():
    """The other half: a complete request must not inherit the old filters."""
    state, _ = _state_after("Show AR_YD_Suiting items", SQL_LIST)
    state, _ = _state_after("only the active ones", SQL_ACTIVE, 19, state=state)
    decision, _ = classify_turn("Show AR_NPD_Shirting items", state, GAZ)
    assert decision == "switch", "a self-contained request starts clean"


def test_explicit_reset_wording_starts_a_new_block():
    state, _ = _state_after("Show AR_YD_Suiting items", SQL_LIST)
    assert classify_turn("New question: show AR_NPD_Shirting items", state, GAZ)[0] == "new_block"


def test_a_long_self_contained_question_is_not_a_follow_up():
    state, _ = _state_after("Show AR_YD_Suiting items", SQL_LIST)
    decision, _ = classify_turn(
        "Which department has the largest number of open tasks across the whole system?",
        state, GAZ)
    assert decision == "new_block"


# ------------------------------------------------------------ sql parsing ----

def test_parse_sql_state_extracts_the_shape():
    parsed = parse_sql_state(
        "SELECT business_unit, COUNT(*) FROM tms_business_object_flat "
        "WHERE business_object_type = 'AR_YD_Suiting' "
        "GROUP BY business_unit ORDER BY business_unit DESC LIMIT 5"
    )
    assert parsed["tables"] == ["tms_business_object_flat"]
    assert "business_object_type" in parsed["filters"]
    assert parsed["grouping"] == ["business_unit"]
    assert parsed["limit"] == 5
    assert parsed["intent"] == "breakdown"


def test_parse_sql_state_marks_a_bare_count_as_aggregate():
    assert parse_sql_state("SELECT COUNT(*) FROM tms_task_flat")["intent"] == "aggregate"


def test_parse_sql_state_survives_unparseable_sql():
    assert parse_sql_state("this is not sql")["tables"] == []
    assert parse_sql_state("")["tables"] == []


# ------------------------------------------------------------------ state ----

def test_follow_up_filters_accumulate():
    state, _ = _state_after("Show AR_YD_Suiting items", SQL_LIST)
    state, _ = _state_after("only the active ones", SQL_ACTIVE, 19, state=state)
    assert "business_object_type" in state.active_filters
    assert "business_object_status" in state.active_filters


def test_a_filter_can_be_removed():
    """Regression: filters used to merge, so a dropped filter came straight back.

    Turn 2 narrows to PVH, turn 3 drops it. The state after turn 3 must not
    still claim PVH is in force, or turn 4 is told to re-apply it.
    """
    with_pvh = (
        "SELECT business_object_id FROM tms_business_object_flat "
        "WHERE business_object_type = 'AR_YD_Suiting' AND business_unit = 'PVH'"
    )
    state, _ = _state_after("Show AR_YD_Suiting items", SQL_LIST)
    state, _ = _state_after("only PVH", with_pvh, 1, state=state)
    assert "business_unit" in state.active_filters

    state, _ = _state_after("drop the business unit filter", SQL_LIST, 22, state=state)
    assert "business_unit" not in state.active_filters
    assert "business_object_type" in state.active_filters
    assert "PVH" not in render_context(state)


def test_switching_subject_drops_the_old_filters():
    """The whole point of a switch: Active must not leak onto the new subject."""
    state, _ = _state_after("Show AR_YD_Suiting items", SQL_LIST)
    state, _ = _state_after("only the active ones", SQL_ACTIVE, 19, state=state)
    state, decision = _state_after(
        "Show AR_NPD_Shirting items",
        "SELECT business_object_id FROM tms_business_object_flat "
        "WHERE business_object_type = 'AR_NPD_Shirting'",
        10, state=state)
    assert decision == "switch"
    assert state.active_entity == "AR_NPD_Shirting"
    assert "AR_YD_Suiting" not in str(state.active_filters)
    assert state.turns_in_block == 1


# ---------------------------------------------------------------- render ----

def test_render_is_empty_before_anything_happens():
    assert render_context(ConversationState()) == ""


def test_render_carries_what_a_follow_up_needs():
    state, _ = _state_after("Show AR_YD_Suiting items", SQL_LIST)
    text = render_context(state)
    assert "AR_YD_Suiting" in text
    assert "tms_business_object_flat" in text
    assert "previous query" in text


def test_context_size_does_not_grow_with_turn_count():
    """The reason this module exists: turn 20 must not cost more than turn 2."""
    state = ConversationState()
    sizes = []
    for i in range(20):
        state, _ = _state_after(f"only the active ones {i}", SQL_ACTIVE, 19, state=state)
        sizes.append(len(render_context(state)))
    assert state.turns_in_block == 20
    # Allow a little jitter, but nothing resembling linear growth.
    assert max(sizes) - min(sizes) < 60, sizes
    assert max(sizes) < 1200, max(sizes)


# ------------------------------------------------- new topic mid-conversation

def _thread_about_business_objects():
    """State after two turns narrowing AR_YD_Suiting by delay and due date."""
    state = ConversationState()
    update_state(
        state, "Show delayed AR_YD_Suiting items",
        "SELECT business_object_id FROM tms_business_object_flat "
        "WHERE business_object_type = 'AR_YD_Suiting' AND delayed_task_count > 0",
        14, "AR_YD_Suiting", "new_block")
    update_state(
        state, "Only those above 10 days",
        "SELECT business_object_id FROM tms_business_object_flat "
        "WHERE business_object_type = 'AR_YD_Suiting' AND delayed_task_count > 0 "
        "AND days_to_due_date > 10",
        6, "AR_YD_Suiting", "follow_up")
    return state


def test_a_complete_request_about_another_entity_starts_a_new_block():
    """"Show my active tasks" is a new question, not a refinement.

    It names its own subject and its own verb, so nothing about the business
    object thread applies to it. Classified as a follow-up it inherited
    business_object_type, delayed_task_count and days_to_due_date -- three
    filters from a different entity -- which is the state leakage the brief
    describes.
    """
    state = _thread_about_business_objects()
    decision, _ = classify_turn("Show my active tasks", state, GAZ)
    assert decision == "new_block"


def test_a_bare_fragment_still_continues_the_block():
    """The counterpart. "How many?" has no subject of its own and must not reset.

    This is the case the old length heuristic existed to catch, and seventeen
    turns across the three suites depend on it.
    """
    state = _thread_about_business_objects()
    for fragment in ("How many?", "How many are there?", "Make that 10",
                     "Show their status too", "How many tasks?"):
        decision, _ = classify_turn(fragment, state, GAZ)
        assert decision == "follow_up", f"{fragment!r} should continue the block"


def test_a_question_the_system_asked_is_carried_into_the_next_turn():
    """A clarification with no candidates still has to be answerable.

    Asked "which user had most tasks, or which department?", the user replied
    "both" -- and that turn was rendered with only the state: filters none,
    last intent list, previous result 63 rows. The question that prompted the
    reply was nowhere in it, so the model asked again and the user had to
    restate the whole thing. Entity clarifications resolved fine because they
    carry candidates to match against; prose ones had nothing.
    """
    state = ConversationState()
    update_state(state, "which user had most tasks, or which department?",
                 None, None, None, "new_block")
    state.awaiting_answer_to = ("Do you want the user with the most tasks, "
                                "or the department with the most tasks?")

    context = render_context(state)

    assert "Do you want the user with the most tasks" in context
    assert "answer" in context.lower(), "the block must say what the reply is for"


def test_an_outstanding_question_allows_asking_again():
    """A reply that answers nothing must not be forced into an answer.

    Recovered from a real session. The system asked whether to "list the
    business objects with open_task_count > 4, or group them by some field",
    and the user replied "3" -- which answers neither. The turn came back as
    SELECT ... LIMIT 3: valid SQL, and an invention.

    The context block was part of the cause. It asserted outright that the
    next question *is* the answer, and the system prompt separately warns that
    asking for clarification when the answer is obvious is as unhelpful as
    guessing. Between them the model had no licence to say "that is not an
    answer to what I asked".
    """
    state = ConversationState()
    state.awaiting_answer_to = (
        "Do you want the business objects with open_task_count > 4, "
        "or grouped by some field?"
    )

    context = render_context(state)

    assert "open_task_count > 4" in context, "the question itself must travel"
    lowered = context.lower()
    assert "ask again" in lowered, (
        "the block must permit re-asking; without it a reply that answers "
        "nothing gets forced into an interpretation"
    )
