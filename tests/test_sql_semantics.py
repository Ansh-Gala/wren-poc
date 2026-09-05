"""The semantic comparer must be strict about meaning and blind to style.

Both halves matter equally. A comparer that flags every reformatting is
useless, and one that waves through a different filter column is worse than
useless because it hides the failure it was built to find.
"""

import pytest

from benchmark.sql_semantics import (
    PROJECTION_EXACT, PROJECTION_MISSING, PROJECTION_SUBSTITUTED,
    PROJECTION_SUPERSET, compare, signature,
)

BASE = ("SELECT business_object_id, business_object_ref_id "
        "FROM tms_business_object_flat "
        "WHERE business_object_type = 'AR_PD_Suiting' "
        "AND business_object_status = 'Closed'")


# ------------------------------------------------- equivalent, must pass ----

def test_identical_sql_is_correct():
    assert compare(BASE, BASE).semantically_correct


def test_formatting_and_case_are_ignored():
    other = ("select business_object_id,   business_object_ref_id\n"
             "from tms_business_object_flat\n"
             "where business_object_type='AR_PD_Suiting' and business_object_status='Closed'")
    assert compare(BASE, other).semantically_correct


def test_predicate_order_is_ignored():
    other = ("SELECT business_object_id, business_object_ref_id "
             "FROM tms_business_object_flat "
             "WHERE business_object_status = 'Closed' "
             "AND business_object_type = 'AR_PD_Suiting'")
    assert compare(BASE, other).semantically_correct


def test_table_aliases_are_ignored():
    other = ("SELECT b.business_object_id, b.business_object_ref_id "
             "FROM tms_business_object_flat b "
             "WHERE b.business_object_type = 'AR_PD_Suiting' "
             "AND b.business_object_status = 'Closed'")
    assert compare(BASE, other).semantically_correct


def test_column_aliases_are_ignored():
    a = "SELECT COUNT(*) FROM tms_task_flat WHERE task_status = 'open'"
    b = "SELECT COUNT(*) AS open_task_count FROM tms_task_flat WHERE task_status = 'open'"
    assert compare(a, b).semantically_correct


def test_count_star_and_count_one_agree():
    a = "SELECT COUNT(*) FROM tms_task_flat"
    b = "SELECT COUNT(1) FROM tms_task_flat"
    assert compare(a, b).semantically_correct


def test_join_direction_is_ignored():
    a = ("SELECT b.business_object_id FROM tms_business_object_flat b "
         "JOIN tms_business_object_attributes_flat a "
         "ON a.business_object_id = b.business_object_id")
    b = ("SELECT b.business_object_id FROM tms_business_object_attributes_flat a "
         "JOIN tms_business_object_flat b "
         "ON b.business_object_id = a.business_object_id")
    assert compare(a, b).semantically_correct


def test_order_by_alias_resolves_to_what_it_names():
    """Regression: ORDER BY n and ORDER BY item_count are the same instruction.

    Both alias COUNT(*); comparing the alias text made every alias choice read
    as an ordering difference.
    """
    a = ("SELECT business_object_type, COUNT(*) AS n FROM tms_business_object_flat "
         "GROUP BY business_object_type ORDER BY n DESC LIMIT 3")
    b = ("SELECT business_object_type, COUNT(*) AS item_count FROM tms_business_object_flat "
         "GROUP BY business_object_type ORDER BY item_count DESC LIMIT 3")
    assert compare(a, b, ordered=True).semantically_correct


def test_order_by_the_aggregate_itself_matches_the_alias():
    a = ("SELECT task_department, COUNT(*) AS n FROM tms_task_flat "
         "GROUP BY task_department ORDER BY n DESC")
    b = ("SELECT task_department, COUNT(*) FROM tms_task_flat "
         "GROUP BY task_department ORDER BY COUNT(*) DESC")
    assert compare(a, b, ordered=True).semantically_correct


def test_bare_boolean_predicate_equals_is_true():
    """Regression: WHERE flag and WHERE flag = TRUE are one test, not two."""
    a = "SELECT COUNT(*) FROM tms_task_flat WHERE is_not_started_task"
    b = "SELECT COUNT(*) FROM tms_task_flat WHERE is_not_started_task = TRUE"
    c = "SELECT COUNT(*) FROM tms_task_flat WHERE is_not_started_task IS TRUE"
    assert compare(a, b).semantically_correct
    assert compare(a, c).semantically_correct


# ------------------------------------------ semantically wrong, must fail ----

def test_a_different_filter_column_is_caught():
    """The E13 case: right rows, wrong column.

    workflow_code and business_object_type agree on this data, so the query
    returned the correct four rows and result comparison passed it. It is
    still wrong.
    """
    wrong = ("SELECT business_object_id, business_object_ref_id "
             "FROM tms_business_object_flat "
             "WHERE workflow_code = 'AR_PD_Suiting' "
             "AND business_object_status = 'Closed'")
    c = compare(BASE, wrong)
    assert not c.semantically_correct
    assert not c.filters_match
    assert any("unexpected column" in i for i in c.issues)


def test_a_different_filter_value_is_caught():
    wrong = BASE.replace("'Closed'", "'Active'")
    c = compare(BASE, wrong)
    assert not c.semantically_correct
    assert not c.filters_match


def test_a_missing_filter_is_caught():
    wrong = ("SELECT business_object_id, business_object_ref_id "
             "FROM tms_business_object_flat WHERE business_object_type = 'AR_PD_Suiting'")
    c = compare(BASE, wrong)
    assert not c.semantically_correct
    assert any("missing filter" in i for i in c.issues)


def test_a_different_table_is_caught():
    """E59: departments from tms_role_flat instead of tms_task_flat."""
    a = "SELECT COUNT(DISTINCT task_department) FROM tms_task_flat"
    b = "SELECT COUNT(DISTINCT department) FROM tms_role_flat"
    c = compare(a, b)
    assert not c.semantically_correct
    assert not c.tables_match


def test_a_different_aggregate_is_caught():
    a = "SELECT COUNT(*) FROM tms_task_flat"
    b = "SELECT SUM(task_id) FROM tms_task_flat"
    assert not compare(a, b).semantically_correct


def test_a_different_grouping_is_caught():
    a = ("SELECT business_object_status, COUNT(*) FROM tms_business_object_flat "
         "GROUP BY business_object_status")
    b = ("SELECT business_unit, COUNT(*) FROM tms_business_object_flat "
         "GROUP BY business_unit")
    c = compare(a, b)
    assert not c.semantically_correct
    assert not c.grouping_match


def test_a_different_limit_is_caught():
    a = "SELECT business_object_id FROM tms_business_object_flat LIMIT 5"
    b = "SELECT business_object_id FROM tms_business_object_flat LIMIT 10"
    assert not compare(a, b).semantically_correct


def test_ordering_is_checked_only_when_the_question_asked_for_it():
    a = "SELECT business_object_id FROM tms_business_object_flat ORDER BY business_object_id ASC"
    b = "SELECT business_object_id FROM tms_business_object_flat ORDER BY business_object_id DESC"
    assert compare(a, b, ordered=False).semantically_correct
    assert not compare(a, b, ordered=True).semantically_correct


def test_a_wrong_join_condition_is_caught():
    a = ("SELECT t.task_id FROM tms_task_flat t JOIN tms_business_object_flat b "
         "ON t.bo_id = b.business_object_id")
    b = ("SELECT t.task_id FROM tms_task_flat t JOIN tms_business_object_flat b "
         "ON t.assigned_user_id = b.business_object_id")
    c = compare(a, b)
    assert not c.semantically_correct
    assert not c.joins_match


# ----------------------------------------------------------- projection ----

def test_projection_verdicts():
    exact = "SELECT business_object_id, business_object_ref_id FROM tms_business_object_flat"
    assert compare(exact, exact).projection_verdict == PROJECTION_EXACT

    superset = ("SELECT business_object_id, business_object_ref_id, business_unit "
                "FROM tms_business_object_flat")
    assert compare(exact, superset).projection_verdict == PROJECTION_SUPERSET

    missing = "SELECT business_object_id FROM tms_business_object_flat"
    assert compare(exact, missing).projection_verdict == PROJECTION_MISSING

    substituted = "SELECT business_object_id, business_unit FROM tms_business_object_flat"
    assert compare(exact, substituted).projection_verdict == PROJECTION_SUBSTITUTED


def test_projection_counts_only_when_the_question_named_its_columns():
    """"Show the items" does not say which columns; "show the id and status" does.

    Judging the first strictly measured our arbitrary choice of ground-truth
    columns rather than the model, and moved with run-to-run variation. The
    verdict is still reported in both cases.
    """
    exact = "SELECT business_object_id, business_object_ref_id FROM tms_business_object_flat"
    missing = "SELECT business_object_id FROM tms_business_object_flat"
    substituted = "SELECT business_object_id, business_unit FROM tms_business_object_flat"

    for wrong in (missing, substituted):
        loose = compare(exact, wrong, strict_projection=False)
        assert loose.semantically_correct, "unspecified columns: any reasonable list answers it"
        assert loose.projection_verdict in (PROJECTION_MISSING, PROJECTION_SUBSTITUTED)

        strict = compare(exact, wrong, strict_projection=True)
        assert not strict.semantically_correct, "named columns: a different list is wrong"


def test_a_superset_projection_is_tolerated_but_reported():
    """Extra columns are untidy, not wrong -- but they must still be visible."""
    exact = "SELECT business_object_id FROM tms_business_object_flat"
    superset = "SELECT business_object_id, business_unit FROM tms_business_object_flat"
    c = compare(exact, superset)
    assert c.semantically_correct
    assert any("extra column" in i for i in c.issues)


# ---------------------------------------------------------------- misc ----

def test_unparseable_sql_is_reported_not_crashed():
    c = compare("SELECT 1 FROM t", "this is not sql at all ((")
    assert not c.parsed
    assert not c.semantically_correct


def test_missing_sql_is_reported():
    assert not compare("SELECT 1 FROM t", None).semantically_correct


def test_signature_extracts_the_pieces():
    s = signature(
        "SELECT business_unit, COUNT(*) FROM tms_business_object_flat "
        "WHERE business_object_status = 'Active' GROUP BY business_unit "
        "ORDER BY business_unit DESC LIMIT 5"
    )
    assert s.tables == {"tms_business_object_flat"}
    assert ("count", "*") in s.aggregates
    assert any(f[0].endswith("business_object_status") for f in s.filters)
    assert any(g.endswith("business_unit") for g in s.grouping)
    assert s.limit == 5


# ------------------------------------------------- clarification parsing ----

def test_a_clarification_is_not_mistaken_for_sql():
    """Regression: parse_sql lifted a fragment out of clarifying prose.

    Both of these were correct clarifications, and the looser fallbacks
    scraped a phrase from the text; the runner then saw "SQL was produced" and
    scored a correct refusal as a silent substitution.
    """
    from claude.parser import parse_clarification

    for raw in (
        """{"clarify": "There is no SLA status value 'Breached'. """
        """Did you mean tasks with SLA status 'Delayed'?"}""",
        """{"clarify": "'Top performers' is not a defined metric - did you mean """
        """users with the most closed tasks, fewest delayed tasks, or something else?"}""",
    ):
        assert parse_clarification(raw) is not None, raw[:50]


def test_an_answer_that_explains_itself_is_still_an_answer():
    from claude.parser import parse_clarification
    raw = '{"sql": "SELECT 1 FROM tms_task_flat"}  (note: did you want closed tasks too?)'
    assert parse_clarification(raw) is None
