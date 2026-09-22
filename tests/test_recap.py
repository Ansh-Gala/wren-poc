"""The conversation's running summary, and why it is a fold rather than a log.

The recap is half of the context the model gets; the user's recent questions
are the other half. They do different jobs, and the difference is the point.

The questions are a transcript. They are exact, and they are the only thing
that can resolve "no, I meant the previous one". But a transcript cannot say
that something has been *undone*: the turn where a user drops a filter leaves
the question that asked for it sitting in the window, unchanged.

The recap can, because it is not a transcript. It is rewritten from scratch
every turn, so the turn that drops the department produces a recap saying the
restriction was removed. That sentence is what stops the model re-applying
what it can still see in the questions above it.

So: the questions carry detail the summary loses, and the summary carries
meaning the questions cannot express. Neither alone is enough.
"""

from __future__ import annotations

import pytest

from pipeline.context import (
    RECAP_MAX_CHARS, ConversationState, accept_recap, render_context,
)


# ------------------------------------------------------------- the guard --

def test_a_clean_recap_is_kept():
    text = "The user is comparing delayed tasks across two departments."
    assert accept_recap(text) == text


def test_a_recap_naming_a_column_is_rejected():
    assert accept_recap("Filtered on task_status = open") is None


def test_a_recap_quoting_sql_is_rejected():
    assert accept_recap("I ran a SELECT over the task table") is None


def test_rejection_means_keep_not_clear():
    """The critical one. A rejected recap must not erase the thread.

    Otherwise the model's single worst turn decides what is remembered.
    """
    state = ConversationState()
    state.rolling_recap = "The user is looking at delayed work."
    accepted = accept_recap("now filtering task_status = open")
    if accepted is not None:          # the shape run_turn uses
        state.rolling_recap = accepted
    assert state.rolling_recap == "The user is looking at delayed work."


def test_an_empty_recap_is_not_a_recap():
    assert accept_recap("") is None
    assert accept_recap(None) is None
    assert accept_recap("   ") is None


def test_a_recap_cannot_grow_without_bound():
    long = "The user keeps asking about more things. " * 40
    assert len(accept_recap(long)) <= RECAP_MAX_CHARS + 3   # + the ellipsis


def test_whitespace_is_flattened():
    assert accept_recap("two\n\n  lines") == "two lines"


# ------------------------------------------------------------ what it does --

def test_the_recap_survives_a_change_of_subject():
    """reset() drops the filters and keeps the recap. That is the point.

    A filter can silently narrow an answer, so a switch must drop it. The
    recap holds no predicate and no SQL, and it is the only thing that can
    bridge "initiative A", "initiative B", "how do those two compare?".
    """
    state = ConversationState()
    state.rolling_recap = "The user has been looking at two initiatives."
    state.active_filters = {"task_status": "task_status = 'open'"}
    state.reset()
    assert state.rolling_recap == "The user has been looking at two initiatives."
    assert state.active_filters == {}


def test_an_explicit_reset_drops_it():
    state = ConversationState()
    state.rolling_recap = "The user has been looking at two initiatives."
    state.forget_history()
    assert state.rolling_recap is None


def test_a_new_block_still_sees_what_the_thread_was_about():
    state = ConversationState()
    state.rolling_recap = "The user has been reviewing delayed work."
    block = render_context(state)
    assert "delayed work" in block
    assert "CONTEXT" in block


def test_the_carryover_carries_no_filter():
    """The whole reason the verbatim window was removed."""
    state = ConversationState()
    state.rolling_recap = "The user has been reviewing delayed work."
    state.active_filters = {"task_department": "task_department = 'Sales'"}
    state.previous_sql = "SELECT 1 FROM tms_task_flat WHERE task_department = 'Sales'"
    block = render_context(state)
    assert "Sales" not in block
    assert "SELECT" not in block


def test_no_recap_means_no_block_at_all():
    assert render_context(ConversationState()) == ""


def test_a_follow_up_sees_the_recap_and_nothing_from_the_last_query():
    state = ConversationState()
    state.rolling_recap = "The user has been reviewing delayed work."
    state.previous_sql = "SELECT 1 FROM tms_task_flat"
    block = render_context(state)
    assert "CONTEXT" in block
    assert "delayed work" in block
    assert "SELECT" not in block
    assert "tms_task_flat" not in block


def test_the_model_is_told_the_recap_is_state_and_not_a_filter():
    """The instruction lives in the cached system prompt, not in every turn.

    It is identical on turn 1 and turn 20, so repeating it per turn would be
    ~350 tokens a question of text that never changes.
    """
    from pipeline.context import CONTEXT_GUIDANCE

    assert "not as a filter" in CONTEXT_GUIDANCE
    assert "still in force" in CONTEXT_GUIDANCE


# ------------------------------------------------------------ the bound --

def test_context_size_stays_flat_however_long_the_conversation_runs():
    """A recap that accumulated would defeat the whole context design."""
    state = ConversationState()
    state.previous_sql = "SELECT 1 FROM tms_task_flat"
    sizes = []
    for turn in range(40):
        accepted = accept_recap(
            "The user is on topic number %d and has asked about several "
            "things along the way." % turn)
        if accepted is not None:
            state.rolling_recap = accepted
        sizes.append(len(render_context(state)))
    assert max(sizes) - min(sizes) < 60, "the block grows with turn count"


@pytest.mark.parametrize("text", [
    "The user asked about Initiative 202 and then about its delayed tasks.",
    "Two departments were compared; the Design team had the most overdue work.",
])
def test_ordinary_business_prose_is_not_mistaken_for_an_identifier(text):
    assert accept_recap(text) == text
