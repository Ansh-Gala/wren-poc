import pytest

from benchmark.questions import load_questions, select, stratified_subset
from benchmark.safety import assert_read_only
from database.connection import run_readonly

QS = load_questions()

def _has_top_level_order_by(sql: str) -> bool:
    """True when the outermost query orders its rows.

    Derived from the SQL rather than the wording, because prose is a poor
    signal: "the highest number of tasks in any workflow" returns one scalar,
    where row order is meaningless. An ORDER BY inside OVER(...) or a subquery
    does not make the result set ordered either, so only the root counts.
    """
    import sqlglot

    try:
        tree = sqlglot.parse_one(sql, read="postgres")
    except Exception:
        return False
    return tree is not None and tree.args.get("order") is not None


def test_question_count_and_id_uniqueness():
    assert len(QS) >= 78
    assert len({q.id for q in QS}) == len(QS)


def test_all_categories_present():
    assert {q.category for q in QS} == set("ABCDEFGHIJKLMNOPQRS")


def test_semantic_questions_document_their_interpretation():
    for q in QS:
        if q.category in ("R", "S"):
            assert q.interpretation, f"{q.id} has no interpretation"
            assert len(q.interpretation.split()) > 10, f"{q.id} interpretation too thin"


def test_ordered_flag_matches_the_expected_sql():
    """`ordered` and a top-level ORDER BY must agree in both directions.

    If they disagree the evaluator scores the wrong thing: a false negative
    when a correct unordered answer is compared as a sequence, or a false
    positive when an ordering the question demanded goes unchecked.
    """
    for q in QS:
        if q.expected_sql is None:
            continue
        has_order = _has_top_level_order_by(q.expected_sql)
        if q.ordered:
            assert has_order, f"{q.id} is marked ordered but its SQL has no ORDER BY"
        elif has_order:
            # An ORDER BY used only to break ties in a LIMIT is fine; anything
            # else means the question really does care about order.
            assert "limit" in q.expected_sql.lower(), (
                f"{q.id} orders its rows but is not marked ordered"
            )


def test_date_questions_are_tagged():
    for q in QS:
        if q.expected_sql is None:
            continue
        if "current_date" in q.expected_sql.lower() or "date_trunc" in q.expected_sql.lower():
            assert "date" in q.tags, f"{q.id} uses date logic but is not tagged"


def test_all_ground_truth_sql_passes_the_read_only_gate():
    for q in QS:
        # Abstention questions carry no SQL: the agent is expected to refuse.
        if q.expected_sql is None:
            continue
        assert_read_only(q.expected_sql)


def test_stratified_subset_is_deterministic_and_covers_categories():
    a = stratified_subset(QS, 25)
    b = stratified_subset(QS, 25)
    assert [q.id for q in a] == [q.id for q in b], "subset is not reproducible"
    assert len(a) == 25
    assert {q.category for q in a} == set("ABCDEFGHIJKLMNOPQRS")


def test_subset_larger_than_pool_returns_everything():
    assert len(stratified_subset(QS, 10_000)) == len(QS)


def test_select_filters_by_category_and_id():
    assert {q.category for q in select(QS, categories="R,S")} == {"R", "S"}
    assert [q.id for q in select(QS, ids=["A01"])] == ["A01"]


# ---- live database checks -------------------------------------------------

@pytest.mark.integration
def test_every_expected_sql_executes(settings):
    failures = []
    for q in QS:
        if q.expected_sql is None:
            continue
        result = run_readonly(settings, q.expected_sql, 15000)
        if result.error:
            failures.append((q.id, result.error.splitlines()[0]))
    assert not failures, failures


@pytest.mark.integration
def test_no_expected_result_is_empty(settings):
    """An empty expected result is passed by almost any wrong query."""
    empty = [q.id for q in QS
             if q.expected_sql is not None
             and not run_readonly(settings, q.expected_sql, 15000).rows]
    assert not empty, f"vacuous questions: {empty}"


@pytest.mark.integration
def test_expected_results_are_stable_within_a_run(settings):
    for q in QS[:12]:
        if q.expected_sql is None:
            continue
        first = run_readonly(settings, q.expected_sql, 15000)
        second = run_readonly(settings, q.expected_sql, 15000)
        assert first.rows == second.rows, f"{q.id} is not stable"
