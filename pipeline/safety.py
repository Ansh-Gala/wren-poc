"""Read-only gate for generated SQL.

The benchmark must never modify the database. Three independent layers stand in
the way, and this module is the first:

1. this AST gate,
2. a PostgreSQL role holding only SELECT,
3. a READ ONLY transaction with a statement timeout.

The AST check is primary. A keyword regex backs it up, so a statement that
sqlglot mis-parses still cannot smuggle a write through.
"""

from __future__ import annotations

import re

import sqlglot
from sqlglot import exp

FORBIDDEN_KEYWORDS = (
    "INSERT", "UPDATE", "DELETE", "DROP", "ALTER", "TRUNCATE",
    "CREATE", "GRANT", "REVOKE", "MERGE", "COPY", "CALL", "DO",
    "VACUUM", "REINDEX", "REFRESH", "COMMENT", "SECURITY",
)

# Node types that mutate schema or data. Checked against the parsed tree, so a
# column merely *named* "update" cannot trigger a false positive.
_FORBIDDEN_NODES = tuple(
    node
    for node in (
        getattr(exp, name, None)
        for name in (
            "Insert", "Update", "Delete", "Drop", "Alter", "AlterTable",
            "TruncateTable", "Create", "Grant", "Revoke", "Merge", "Copy",
            "Command", "Transaction", "Commit", "Rollback", "Set", "SetItem",
            "Use", "Attach", "Detach",
        )
    )
    if node is not None
)

_KEYWORD_RE = re.compile(
    r"(?<![A-Za-z0-9_])(" + "|".join(FORBIDDEN_KEYWORDS) + r")(?![A-Za-z0-9_])",
    re.IGNORECASE,
)
_LINE_COMMENT = re.compile(r"--[^\n]*")
_BLOCK_COMMENT = re.compile(r"/\*.*?\*/", re.DOTALL)
_STRING_LITERAL = re.compile(r"'(?:[^']|'')*'")


class UnsafeSQLError(Exception):
    """Raised when generated SQL is not provably read-only."""


def _strip_noise(sql: str) -> str:
    """Remove comments and string literals before the keyword screen.

    A task named 'Update browser matrix' is legitimate data and must not be
    mistaken for an UPDATE statement.
    """
    sql = _BLOCK_COMMENT.sub(" ", sql)
    sql = _LINE_COMMENT.sub(" ", sql)
    return _STRING_LITERAL.sub("''", sql)


def assert_read_only(sql: str) -> None:
    if not sql or not sql.strip():
        raise UnsafeSQLError("empty SQL")

    try:
        statements = [s for s in sqlglot.parse(sql, read="postgres") if s is not None]
    except Exception as exc:
        raise UnsafeSQLError(f"could not parse SQL: {exc}") from exc

    if not statements:
        raise UnsafeSQLError("no statement found")
    if len(statements) > 1:
        raise UnsafeSQLError(
            f"expected a single statement, found {len(statements)}"
        )

    statement = statements[0]

    if not isinstance(statement, (exp.Select, exp.Union, exp.Subquery)) and not (
        isinstance(statement, exp.Query)
    ):
        raise UnsafeSQLError(
            f"statement is {type(statement).__name__}, expected a query"
        )

    for node_type in _FORBIDDEN_NODES:
        found = statement.find(node_type)
        if found is not None:
            raise UnsafeSQLError(
                f"statement contains a {type(found).__name__} node"
            )

    screened = _strip_noise(sql)
    match = _KEYWORD_RE.search(screened)
    if match:
        raise UnsafeSQLError(f"forbidden keyword '{match.group(1).upper()}'")
