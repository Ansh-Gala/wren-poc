from benchmark.classify import classify_failure, is_heuristic
from benchmark.models import QuestionResult


def make(**kw):
    base = dict(
        sql_valid=True, execution_success=True, result_match=False,
        generated_sql="SELECT 1", expected_sql="SELECT 1",
        sqlstate=None, timed_out=False, cli_ok=True,
        parse_strategy="json", tools_used=[], mcp_errors=[], category="A", tags=[],
    )
    base.update(kw)
    return QuestionResult(**base)


# ---- deterministic signals -------------------------------------------------

def test_timeout_wins_over_everything():
    assert classify_failure(make(timed_out=True, cli_ok=False)) == "TIMEOUT"


def test_cli_failure():
    assert classify_failure(make(cli_ok=False)) == "CLI_FAILURE"


def test_parser_failure():
    assert classify_failure(make(parse_strategy="none", generated_sql=None)) == "PARSER_FAILURE"


def test_wren_failure_when_tool_errored_and_no_sql():
    r = make(parse_strategy="none", generated_sql=None,
             mcp_errors=["wren: model not found"])
    assert classify_failure(r) == "WREN_FAILURE"


def test_unsafe_sql_is_invalid():
    assert classify_failure(make(sql_valid=False)) == "INVALID_SQL"


def test_undefined_table_sqlstate():
    r = make(execution_success=False, sqlstate="42P01",
             generated_sql="SELECT * FROM tasks")
    assert classify_failure(r) == "WRONG_TABLE"


def test_undefined_table_on_unknown_table_is_hallucination():
    r = make(execution_success=False, sqlstate="42P01",
             generated_sql="SELECT * FROM projects")
    assert classify_failure(r) == "HALLUCINATED_SCHEMA"


def test_undefined_column_sqlstate():
    assert classify_failure(make(execution_success=False, sqlstate="42703")) == "WRONG_COLUMN"


def test_grouping_error_sqlstate():
    assert classify_failure(make(execution_success=False, sqlstate="42803")) == "WRONG_GROUPING"


def test_syntax_error_sqlstate():
    assert classify_failure(make(execution_success=False, sqlstate="42601")) == "INVALID_SQL"


def test_statement_timeout_sqlstate():
    assert classify_failure(make(execution_success=False, sqlstate="57014")) == "TIMEOUT"


def test_unknown_sqlstate_falls_back_to_invalid_sql():
    assert classify_failure(make(execution_success=False, sqlstate="XX999")) == "INVALID_SQL"


# ---- heuristic signals -----------------------------------------------------

def test_owner_assignee_confusion_is_a_business_rule_failure():
    r = make(
        tags=["semantic"],
        expected_sql="SELECT u.full_name FROM workflows w "
                     "JOIN users u ON u.id = w.owner_user_id",
        generated_sql="SELECT u.full_name FROM tasks t "
                      "JOIN users u ON u.id = t.assigned_user_id",
    )
    assert classify_failure(r) == "WRONG_BUSINESS_RULE"


def test_missing_join_detected():
    r = make(
        expected_sql="SELECT u.full_name FROM users u "
                     "JOIN tasks t ON t.assigned_user_id = u.id",
        generated_sql="SELECT full_name FROM users",
    )
    assert classify_failure(r) == "MISSING_JOIN"


def test_extra_table_is_wrong_table():
    r = make(
        expected_sql="SELECT full_name FROM users",
        generated_sql="SELECT u.full_name FROM users u "
                      "JOIN tasks t ON t.assigned_user_id = u.id",
    )
    assert classify_failure(r) == "WRONG_TABLE"


def test_hallucinated_table_in_running_query():
    r = make(
        expected_sql="SELECT full_name FROM users",
        generated_sql="SELECT name FROM projects",
    )
    assert classify_failure(r) == "HALLUCINATED_SCHEMA"


def test_cte_name_is_not_mistaken_for_a_hallucinated_table():
    r = make(
        expected_sql="SELECT count(*) FROM tasks",
        generated_sql="WITH open_tasks AS (SELECT * FROM tasks) "
                      "SELECT count(*) FROM open_tasks",
    )
    assert classify_failure(r) != "HALLUCINATED_SCHEMA"


def test_wrong_aggregation_detected():
    r = make(
        expected_sql="SELECT count(id) FROM tasks",
        generated_sql="SELECT sum(id) FROM tasks",
    )
    assert classify_failure(r) == "WRONG_AGGREGATION"


def test_wrong_filter_detected():
    r = make(
        expected_sql="SELECT id FROM tasks WHERE status = 'BLOCKED'",
        generated_sql="SELECT id FROM tasks WHERE status = 'TODO'",
    )
    assert classify_failure(r) == "WRONG_FILTER"


def test_missing_filter_detected():
    r = make(
        expected_sql="SELECT id FROM tasks WHERE status = 'BLOCKED'",
        generated_sql="SELECT id FROM tasks",
    )
    assert classify_failure(r) == "WRONG_FILTER"


def test_wrong_date_logic_detected():
    r = make(
        tags=["date"],
        expected_sql="SELECT id FROM tasks WHERE due_date < CURRENT_DATE",
        generated_sql="SELECT id FROM tasks WHERE due_date IS NOT NULL",
    )
    assert classify_failure(r) == "WRONG_DATE_LOGIC"


def test_unexplained_mismatch_is_an_honest_default():
    assert classify_failure(make()) == "RESULT_MISMATCH"


def test_heuristic_flagging():
    assert not is_heuristic("TIMEOUT")
    assert not is_heuristic("WRONG_TABLE")
    assert is_heuristic("RESULT_MISMATCH")
    assert is_heuristic("WRONG_BUSINESS_RULE")
