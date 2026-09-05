"""Extract SQL from Claude's reply.

The prompt asks for ``{"sql": "..."}``, but an agentic CLI session is free-form
text and will not always comply. Five ordered strategies are tried, each a
separate function so each is independently testable. ``ParsedSQL.strategy``
records which one matched, which turns parser fragility into a measurable
outcome rather than an invisible failure.
"""

from __future__ import annotations

import json
import re

import sqlglot
from sqlglot import exp

from benchmark.models import ParsedSQL

_SQL_START = re.compile(r"\b(SELECT|WITH)\b", re.IGNORECASE)
_FENCE = re.compile(r"```([A-Za-z0-9_+-]*)[ \t]*\r?\n(.*?)```", re.DOTALL)
_LINE_COMMENT = re.compile(r"--[^\n]*")
_BLOCK_COMMENT = re.compile(r"/\*.*?\*/", re.DOTALL)


def _clean(sql: str) -> str:
    """Strip SQL comments, surrounding whitespace and a trailing semicolon."""
    sql = _BLOCK_COMMENT.sub("", sql)
    sql = _LINE_COMMENT.sub("", sql)
    sql = sql.strip()
    while sql.endswith(";"):
        sql = sql[:-1].rstrip()
    return sql.strip()


def _looks_like_sql(text: str) -> bool:
    m = _SQL_START.search(text)
    return m is not None and m.start() == 0


def _from_json_object(obj: object) -> str | None:
    if isinstance(obj, dict):
        for key in ("sql", "query", "generated_sql"):
            value = obj.get(key)
            if isinstance(value, str) and value.strip():
                return value
    return None


def _strategy_json(text: str) -> str | None:
    """Whole reply is a JSON object carrying the SQL."""
    try:
        return _from_json_object(json.loads(text.strip()))
    except (json.JSONDecodeError, ValueError):
        return None


def _strategy_sql_fence(text: str) -> str | None:
    """Last ```sql fenced block. Last, because a model often revises itself."""
    blocks = [body for lang, body in _FENCE.findall(text) if lang.lower() in {"sql", "postgresql", "postgres"}]
    return blocks[-1] if blocks else None


def _strategy_generic_fence(text: str) -> str | None:
    """Last fenced block of any language that actually looks like SQL."""
    blocks = [body for _, body in _FENCE.findall(text) if _looks_like_sql(_clean(body))]
    return blocks[-1] if blocks else None


def _strategy_embedded_json(text: str) -> str | None:
    """A JSON object somewhere inside prose."""
    for match in re.finditer(r"\{", text):
        depth = 0
        for i in range(match.start(), len(text)):
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
                if depth == 0:
                    try:
                        found = _from_json_object(json.loads(text[match.start(): i + 1]))
                    except (json.JSONDecodeError, ValueError):
                        break
                    if found:
                        return found
                    break
    return None


def _parses_as_single_query(sql: str) -> bool:
    try:
        statements = [s for s in sqlglot.parse(sql, read="postgres") if s is not None]
    except Exception:
        return False
    return len(statements) == 1 and isinstance(statements[0], exp.Query)


def _strategy_bare(text: str) -> str | None:
    """Bare SELECT/WITH statement in prose.

    Candidates are tried earliest-first and validated by actually parsing them.
    Taking the *last* match would decapitate a CTE -- "WITH c AS (...) SELECT
    ... FROM c" would yield only the trailing SELECT, referencing a CTE that no
    longer exists. Parsing also stops the word "with" in ordinary prose from
    being mistaken for the start of a statement.
    """
    stripped = _clean(text)
    matches = list(_SQL_START.finditer(stripped))
    if not matches:
        return None

    for match in matches:
        candidate = stripped[match.start():].strip()
        if _parses_as_single_query(candidate):
            return candidate

    # Nothing parsed; fall back to the last match so the failure is still
    # recorded as generated SQL rather than a parser miss.
    return stripped[matches[-1].start():]


_STRATEGIES = (
    ("json", _strategy_json),
    ("sql_fence", _strategy_sql_fence),
    ("generic_fence", _strategy_generic_fence),
    ("embedded_json", _strategy_embedded_json),
    ("bare", _strategy_bare),
)


def parse_sql(text: str) -> ParsedSQL:
    if not text or not text.strip():
        return ParsedSQL(sql=None, strategy="none", raw=text or "")

    for name, strategy in _STRATEGIES:
        try:
            candidate = strategy(text)
        except Exception:  # a malformed reply must not crash the benchmark
            candidate = None
        if not candidate:
            continue
        cleaned = _clean(candidate)
        if cleaned and _looks_like_sql(cleaned):
            return ParsedSQL(sql=cleaned, strategy=name, raw=text)

    return ParsedSQL(sql=None, strategy="none", raw=text)
