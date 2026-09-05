"""Failure classification.

Two tiers, and the report says which is which:

**Deterministic.** TIMEOUT, CLI_FAILURE, WREN_FAILURE, PARSER_FAILURE,
INVALID_SQL and the SQLSTATE-derived categories are read from facts -- a
process that timed out, a tool that returned an error, a gate that refused the
statement, a code PostgreSQL itself returned. These are reliable.

**Heuristic.** When a query ran cleanly but returned the wrong rows, the reason
is inferred by diffing the generated SQL against the expected SQL with sqlglot.
That inference can be wrong: there are many correct ways to write a query, and
a structural difference is not proof of the cause. Anything not confidently
identified is reported as RESULT_MISMATCH rather than guessed at, and every
record keeps the raw output so a human can overrule the label.

Do not read the heuristic categories as ground truth about *why* a model
failed. They are a triage aid for finding patterns worth reading by hand.
"""

from __future__ import annotations

import sqlglot
from sqlglot import exp

from benchmark.models import QuestionResult

KNOWN_TABLES = {"users", "workflows", "tasks"}

# PostgreSQL error codes -> category. Deterministic: PostgreSQL told us.
SQLSTATE_CATEGORIES = {
    "42P01": "WRONG_TABLE",          # undefined_table
    "42703": "WRONG_COLUMN",         # undefined_column
    "42803": "WRONG_GROUPING",       # grouping_error
    "42P10": "WRONG_GROUPING",       # invalid_column_reference
    "42601": "INVALID_SQL",          # syntax_error
    "42883": "WRONG_COLUMN",         # undefined_function
    "42702": "WRONG_COLUMN",         # ambiguous_column
    "42P18": "INVALID_SQL",          # indeterminate_datatype
    "22007": "WRONG_DATE_LOGIC",     # invalid_datetime_format
    "22008": "WRONG_DATE_LOGIC",     # datetime_field_overflow
    "57014": "TIMEOUT",              # query_canceled (statement_timeout)
}

DETERMINISTIC = {
    "TIMEOUT", "CLI_FAILURE", "WREN_FAILURE", "PARSER_FAILURE", "INVALID_SQL",
    "WRONG_TABLE", "WRONG_COLUMN", "WRONG_GROUPING", "HALLUCINATED_SCHEMA",
}

_DATE_TOKENS = ("current_date", "now(", "date_trunc", "interval", "age(", "extract(")


def _parse(sql: str | None):
    if not sql:
        return None
    try:
        return sqlglot.parse_one(sql, read="postgres")
    except Exception:
        return None


def _tables(tree) -> set[str]:
    if tree is None:
        return set()
    names = set()
    for table in tree.find_all(exp.Table):
        name = table.name
        if name:
            names.add(name.lower())
    # CTE names are not base tables and must not count as hallucinations.
    for cte in tree.find_all(exp.CTE):
        if cte.alias:
            names.discard(cte.alias.lower())
    return names


def _join_count(tree) -> int:
    return 0 if tree is None else len(list(tree.find_all(exp.Join)))


def _aggregates(tree) -> set[str]:
    if tree is None:
        return set()
    found = set()
    for node in tree.find_all(exp.AggFunc):
        found.add(type(node).__name__.lower())
    return found


def _group_keys(tree) -> int:
    if tree is None:
        return 0
    return sum(len(g.expressions) for g in tree.find_all(exp.Group))


def _has_date_logic(sql: str) -> bool:
    lowered = (sql or "").lower()
    return any(token in lowered for token in _DATE_TOKENS)


def _owner_assignee_confusion(expected_sql: str, generated_sql: str) -> bool:
    """The schema's signature mistake: owner substituted for assignee, or vice versa.

    Detected only when one query uses one relationship and the other uses the
    other -- not merely when they differ in some way.
    """
    e, g = (expected_sql or "").lower(), (generated_sql or "").lower()
    owner_e, owner_g = "owner_user_id" in e, "owner_user_id" in g
    assignee_e, assignee_g = "assigned_user_id" in e, "assigned_user_id" in g
    return (owner_e and not owner_g and assignee_g) or (
        assignee_e and not assignee_g and owner_g
    )


def classify_failure(result: QuestionResult) -> str:
    # ---- deterministic signals, in order of precedence -------------------
    if result.timed_out:
        return "TIMEOUT"
    if not result.cli_ok:
        return "CLI_FAILURE"

    if result.parse_strategy == "none" or not result.generated_sql:
        # A Wren tool error that left Claude unable to answer is a Wren
        # failure, not a parser failure.
        return "WREN_FAILURE" if result.mcp_errors else "PARSER_FAILURE"

    if not result.sql_valid:
        return "INVALID_SQL"

    if not result.execution_success:
        if result.sqlstate in SQLSTATE_CATEGORIES:
            category = SQLSTATE_CATEGORIES[result.sqlstate]
            if category == "WRONG_TABLE":
                generated = _tables(_parse(result.generated_sql))
                if generated - KNOWN_TABLES:
                    return "HALLUCINATED_SCHEMA"
            return category
        return "INVALID_SQL"

    # ---- heuristic: it ran, but returned the wrong rows -------------------
    expected_tree = _parse(result.expected_sql)
    generated_tree = _parse(result.generated_sql)

    if _owner_assignee_confusion(result.expected_sql, result.generated_sql):
        return "WRONG_BUSINESS_RULE"

    expected_tables = _tables(expected_tree)
    generated_tables = _tables(generated_tree)

    if generated_tables - KNOWN_TABLES:
        return "HALLUCINATED_SCHEMA"
    if generated_tables - expected_tables:
        return "WRONG_TABLE"
    if expected_tables - generated_tables:
        return "MISSING_JOIN"

    if _join_count(expected_tree) != _join_count(generated_tree):
        return "WRONG_JOIN"

    if _aggregates(expected_tree) != _aggregates(generated_tree):
        return "WRONG_AGGREGATION"

    if _group_keys(expected_tree) != _group_keys(generated_tree):
        return "WRONG_GROUPING"

    expected_dates = _has_date_logic(result.expected_sql)
    generated_dates = _has_date_logic(result.generated_sql)
    if expected_dates != generated_dates or (
        expected_dates and "date" in result.tags
    ):
        return "WRONG_DATE_LOGIC"

    if "semantic" in result.tags:
        return "SEMANTIC_MISUNDERSTANDING"

    expected_where = expected_tree.find(exp.Where) if expected_tree else None
    generated_where = generated_tree.find(exp.Where) if generated_tree else None
    if (expected_where is None) != (generated_where is None):
        return "WRONG_FILTER"
    if expected_where is not None and generated_where is not None:
        if expected_where.sql().lower() != generated_where.sql().lower():
            return "WRONG_FILTER"

    if _null_handling_differs(result.expected_sql, result.generated_sql):
        return "WRONG_NULL_HANDLING"

    # Nothing identified it. Say so rather than inventing a reason.
    return "RESULT_MISMATCH"


def _null_handling_differs(expected_sql: str, generated_sql: str) -> bool:
    e, g = (expected_sql or "").lower(), (generated_sql or "").lower()
    for token in ("is null", "is not null", "left join", "coalesce"):
        if (token in e) != (token in g):
            return True
    return False


def is_heuristic(category: str | None) -> bool:
    """Whether a category was inferred rather than observed."""
    return bool(category) and category not in DETERMINISTIC
