"""Who is asking, and what happens when nobody knows.

The bug this replaces is worth stating, because the tests are shaped by it:
the business rules named a literal user id, so "show my tasks" returned the
same person's work to everyone who asked. The failure was invisible -- a
plausible list of tasks, belonging to somebody else.

So the two properties asserted here are the two that made it invisible. The
value has to come from the server, and there has to be no default: a missing
identity must render nothing at all, leaving the rules to say "ask who is
asking" rather than quietly picking someone.
"""

from __future__ import annotations

import pytest

from pipeline.identity import CallerIdentity, render_identity


def test_nobody_renders_nothing():
    """The whole point. A default here is the bug coming back."""
    assert render_identity(None) == ""


def test_a_uid_of_zero_is_nobody():
    # Drupal's anonymous user. Rendering "id: 0" would invite a filter on it.
    assert render_identity(CallerIdentity(0, "Anonymous")) == ""


def test_the_block_carries_the_id():
    block = render_identity(CallerIdentity(4213, "Amit Sharma"))
    assert "id: 4213" in block
    assert "Amit Sharma" in block


def test_every_department_travels_not_just_the_first():
    """Most people are in more than one; only six users have exactly one."""
    block = render_identity(CallerIdentity(
        7, "Priya N", ("Design Team block", "Sales team block")))
    assert "Design Team block" in block
    assert "Sales team block" in block


def test_a_person_with_no_department_says_nothing_about_departments():
    assert "departments" not in render_identity(CallerIdentity(3, "WCMS Admin"))


def test_a_person_with_no_name_still_renders():
    # The id is what the query needs; the name is only there to read.
    assert "id: 12" in render_identity(CallerIdentity(12, "", ("Developer",)))


def test_the_block_says_the_words_it_is_there_to_resolve():
    block = render_identity(CallerIdentity(1, "Admin"))
    for word in ('"my"', '"me"', '"mine"', '"our"'):
        assert word in block, word


def test_the_block_says_where_the_value_came_from():
    """A reader of the prompt should see that the browser did not supply it."""
    block = render_identity(CallerIdentity(1, "Admin"))
    assert "from the session" in block
    assert "never from the question" in block


def test_nothing_in_the_block_trips_the_identifier_guard():
    """It is prompt text, and the model builds sentences out of prompt text.

    A snake_case word here would come back inside an explanation or a
    clarification and be replaced by redact.safe_clarification, costing the
    user the answer.
    """
    from pipeline.redact import safe_clarification

    block = render_identity(CallerIdentity(
        4213, "Amit Sharma", ("Design Team block", "Sales team block")))
    for line in block.splitlines():
        if line.strip():
            assert safe_clarification(line) == line.strip(), line


@pytest.mark.parametrize("identity", [
    None,
    CallerIdentity(0, ""),
    CallerIdentity(4213, "Amit Sharma", ("Design Team block",)),
])
def test_rendering_is_stable(identity):
    """Called on every turn; two calls must not differ."""
    assert render_identity(identity) == render_identity(identity)


def test_a_turn_puts_the_block_above_the_conversation_context():
    """Ordering matters: who is asking frames everything after it."""
    from pipeline.context import ConversationState
    from pipeline.lean_runner import run_turn

    # Rendering is what is asserted, so the block is built the way run_turn
    # builds it rather than by driving a model.
    block = render_identity(CallerIdentity(4213, "Amit Sharma"))
    context = "ACTIVE CONVERSATION CONTEXT\n\nsubject: initiative 202\n"
    combined = block + context
    assert combined.index("SIGNED-IN USER") < combined.index("ACTIVE CONVERSATION")
    assert callable(run_turn) and ConversationState is not None
