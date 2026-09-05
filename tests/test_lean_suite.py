"""The lean suite must stay executable, non-vacuous and internally consistent."""

import pytest

from benchmark.lean_suite import DECISIONS, all_turns, load_suite, select

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

    AR_NPD_Shirting is 5 Active of 10, so a leaked Active filter shows up as
    5 rows instead of 10. A subject with no such split would hide the bug.
    """
    c04 = next(c for c in CONVS if c.id == "C04")
    switch = [t for t in c04.turns if t.expect_decision == "switch"]
    assert switch, "C04 has no switch turn"
    assert "AR_NPD_Shirting" in switch[0].expected_sql
    assert "Active" not in switch[0].expected_sql


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
