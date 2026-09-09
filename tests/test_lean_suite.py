"""The lean suite must stay executable, non-vacuous and internally consistent."""

import pytest

from benchmark.suite import all_turns, load_suite, select
from pipeline.lean_suite import DECISIONS

CONVS = load_suite()
TURNS = all_turns(CONVS)


def test_suite_is_fifty_turns():
    assert len(TURNS) == 50


def test_it_actually_contains_conversations():
    multi = [c for c in CONVS if not c.is_standalone]
    assert len(multi) >= 6, "too few threads to test conversational behaviour"
    assert sum(len(c.turns) for c in multi) >= 20


def test_turn_ids_are_unique():
    ids = [t.id for t in TURNS]
    assert len(set(ids)) == len(ids)


def test_every_turn_has_sql():
    """This suite has no abstention questions; a missing query is a mistake."""
    missing = [t.id for t in TURNS if not t.expected_sql]
    assert not missing, missing


def test_declared_decisions_are_valid():
    for t in TURNS:
        if t.expect_decision is not None:
            assert t.expect_decision in DECISIONS, t.id


def test_first_turn_of_a_thread_opens_a_block():
    for c in CONVS:
        first = c.turns[0]
        if first.expect_decision is not None:
            assert first.expect_decision in ("new_block", "switch"), first.id


def test_threads_declare_their_decisions():
    """Without this the conversational assertions are silently untested."""
    for c in CONVS:
        if c.is_standalone:
            continue
        for t in c.turns:
            assert t.expect_decision is not None, f"{t.id} has no expect_decision"


def test_the_suite_covers_the_required_behaviours():
    cats = " ".join(c.category for c in CONVS).lower()
    for behaviour in ("add filter", "replace", "group", "topic switch",
                      "explicit reset", "limit"):
        assert behaviour in cats, f"no conversation covers {behaviour!r}"


def test_context_leakage_case_is_present_and_discriminating():
    """C04.4 must be answerable wrongly if the previous filter leaks.

    The instrument has to be a status the active-first default never supplies.
    While the thread narrowed on Active, the default put Active on every turn
    and a leaked filter was indistinguishable from a correct answer -- the test
    would have passed whatever the model did. So the previous turn narrows on
    Closed, and the switch must come back to the default: AR_NPD_YD_SHIRTING is
    49 Active and 8 Closed, so a leak reads as 8 where the right answer is 49.

    AR_NPD_Shirting cannot be the subject any more: it splits 5 Active / 5
    Closed, so once the default arrived both the leak and the correct answer
    returned 5 rows and the count could no longer separate them.
    """
    c04 = next(c for c in CONVS if c.id == "C04")
    turns = c04.turns
    index = next((i for i, t in enumerate(turns)
                  if t.expect_decision == "switch"), None)
    assert index is not None, "C04 has no switch turn"
    assert index > 0, "the switch turn has nothing to leak from"
    switch, previous = turns[index], turns[index - 1]

    assert "AR_NPD_YD_SHIRTING" in switch.expected_sql
    assert "'Closed'" in previous.expected_sql, (
        "the turn before the switch must narrow on a status the default does "
        "not supply, or a leak cannot be detected")
    assert "'Closed'" not in switch.expected_sql, "the previous status leaked"
    assert "'Active'" in switch.expected_sql, (
        "the switch should fall back to the active-first default")


def test_selection_returns_whole_conversations():
    """Selecting one turn must pull in the turns it depends on."""
    picked = select(CONVS, ids=["C04.4"])
    assert len(picked) == 1
    assert len(picked[0].turns) == 5


@pytest.mark.integration
def test_every_expected_query_runs_and_returns_rows(settings):
    from database.connection import run_readonly
    broken, empty = [], []
    for t in TURNS:
        res = run_readonly(settings, t.expected_sql, 15000)
        if res.error:
            broken.append((t.id, res.error.splitlines()[0]))
        elif not res.rows:
            empty.append(t.id)
    assert not broken, broken
    assert not empty, f"vacuous questions: {empty}"


def test_a_reset_expectation_never_carries_the_previous_filters():
    """expect_decision and expected_sql must agree about what survives.

    switch and new_block both mean "drop what was narrowing the old subject".
    A turn that claims one of them while its own expected SQL still carries
    the previous turn's filters is asserting two contradictory things, and the
    runner will fail the turn no matter what the model does -- Y05.3 produced
    exactly the right 26 rows and was scored a CONTEXT_ERROR because of it.

    rebase is the decision that means "swap the subject, keep the shape", and
    it is the one such a turn should be asking for.
    """
    from pathlib import Path

    from pipeline.context import parse_sql_state
    from benchmark.suite import load_suite

    # The columns that identify the subject rather than narrow it. These are
    # expected to change on a switch; everything else is expected to vanish.
    #
    # The status columns are here for a different reason: since the
    # active-first default (metadata/business_rules.yaml, default_to_active) a
    # status predicate is re-derived on every turn rather than carried from the
    # one before, so finding one on both sides of a switch is not evidence of a
    # leak. What would be evidence is the *value* surviving, and C04.4 asserts
    # exactly that -- see test_context_leakage_case_is_present_and_discriminating.
    entity_columns = {"business_object_type", "workflow_code", "workflow_name",
                      "business_object_status", "task_status"}

    contradictions = []
    for suite in ("lean_questions.yaml", "targeted_questions.yaml",
                  "expansion_questions.yaml"):
        for conversation in load_suite(Path("benchmark") / suite):
            turns = conversation.turns
            for previous, turn in zip(turns, turns[1:]):
                if turn.expect_decision not in ("switch", "new_block"):
                    continue
                if not (previous.expected_sql and turn.expected_sql):
                    continue
                before = set(parse_sql_state(previous.expected_sql)["filters"])
                after = set(parse_sql_state(turn.expected_sql)["filters"])
                carried = (before & after) - entity_columns
                if carried:
                    contradictions.append(
                        f"{turn.id} expects {turn.expect_decision} but its SQL "
                        f"still carries {sorted(carried)}"
                    )

    assert not contradictions, "\n".join(contradictions)


def test_the_followup_suite_covers_the_dimensions_it_claims_to():
    """Coverage is part of the suite's contract, not an accident of writing it.

    A suite that drifts towards whatever was easy to write stops measuring
    what it was built for, and that is invisible in an accuracy number.
    """
    from pathlib import Path

    from benchmark.suite import all_turns, load_suite

    turns = all_turns(load_suite(Path("benchmark/followup_questions.yaml")))
    assert len(turns) >= 100, f"only {len(turns)} turns"

    categories = " ".join(t.category for t in turns).lower()
    for dimension in ("repair", "clarify", "explore", "mutation",
                      "analytical", "multi-step", "new topic"):
        assert dimension in categories, f"no case covers {dimension}"

    # Every dimension the brief lists as a follow-up move must appear as an
    # action somewhere, or the suite is asserting a narrower contract than the
    # one the frontend is being promised.
    actions = {t.expect_action["type"] for t in turns if t.expect_action}
    assert {"add_filter", "add_group_by", "set_sort", "set_aggregate",
            "remove_filter", "drill_down", "set_entity"} <= actions

    assert sum(1 for t in turns if t.expect_normalized) >= 20
    assert sum(1 for t in turns if t.expect_behavior == "clarify") >= 15
    assert sum(1 for t in turns if t.expect_followup == "exploration") >= 25
