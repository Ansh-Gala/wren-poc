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

from pipeline.models import ParsedSQL

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


# ------------------------------------------------------------- clarification --

_CLARIFY_KEYS = ("clarify", "clarification", "question")


def parse_clarification(text: str) -> str | None:
    """The clarifying question the model asked, if it asked one.

    A system that can only emit SQL has no way to say "which department did
    you mean?", so it guesses, and a guess dressed as SQL is indistinguishable
    from an answer. Allowing {"clarify": "..."} gives it somewhere to put the
    doubt, which is what makes "should not guess" testable at all.

    Only the structured form counts. Prose that happens to contain a question
    mark is not a refusal to answer -- the model often explains itself while
    still returning SQL, and treating that as a clarification would score a
    confident wrong answer as correct restraint.
    """
    if not text:
        return None
    for match in re.finditer(r"\{.*?\}", text, re.DOTALL):
        try:
            obj = json.loads(match.group(0))
        except Exception:
            continue
        if not isinstance(obj, dict):
            continue
        if any(k in obj for k in ("sql", "SQL")):
            return None  # it answered; that is not a clarification
        for key in _CLARIFY_KEYS:
            value = obj.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return None


def _json_objects(text: str) -> list[dict]:
    """The JSON objects in a reply, whole-reply first.

    The whole reply is tried before the fragments because the fragment scan is
    the non-greedy ``\\{.*?\\}`` that parse_clarification uses, which stops at
    the first closing brace and so cannot read a nested object. The readers
    below want flat fields, so that is sufficient for them -- but taking the
    whole reply first means a well-formed answer is read correctly whatever it
    nests.
    """
    objects: list[dict] = []
    if not text:
        return objects
    try:
        whole = json.loads(text.strip())
    except Exception:
        whole = None
    if isinstance(whole, dict):
        objects.append(whole)
    for match in re.finditer(r"\{.*?\}", text, re.DOTALL):
        try:
            obj = json.loads(match.group(0))
        except Exception:
            continue
        if isinstance(obj, dict):
            objects.append(obj)
    return objects


def _parse_string(text: str, key: str) -> str | None:
    """One non-empty string field, or nothing."""
    for obj in _json_objects(text):
        value = obj.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _parse_string_list(text: str, key: str) -> list[str]:
    """A flat list of non-empty strings under one key, or nothing.

    All-or-nothing on purpose. Dropping the malformed entries would offer a
    list missing whichever choice the user was looking for, and a silently
    short list is worse than no list: the schema-derived path can answer
    instead, and does.
    """
    for obj in _json_objects(text):
        raw = obj.get(key)
        if not isinstance(raw, list):
            continue
        values = [v.strip() for v in raw if isinstance(v, str) and v.strip()]
        if len(values) > 1 and len(values) == len(raw):
            return values
    return []


def parse_explanation(text: str) -> str | None:
    """The plain-English account the model gave of what it understood.

    Separate from the SQL rather than derived from it, because the two answer
    different questions: the statement says what will be selected, and this
    says what the user asked for. A sentence generated from the parsed SQL
    could only ever restate the query in words, which is the thing a
    non-technical reader already could not read.
    """
    return _parse_string(text, "explanation")


def parse_goal(text: str) -> str | None:
    """The model's restatement of what the user is after, if it sent one.

    The running goal is otherwise the question that opened the block, which is
    right until a follow-up contradicts it: "open tasks for Sales" then
    "forget the department" leaves a goal still naming Sales beside filters
    that no longer do, and the model is handed a contradiction. Only the model
    can tell that the aim moved, so it is allowed to say so.
    """
    return _parse_string(text, "goal")


def parse_recap(text: str) -> str | None:
    """The model's rewritten summary of the conversation, if it sent one.

    Optional by design. The model is told to leave it out when the thread has
    not moved on from what the recap already says, so most turns send nothing
    and cost nothing -- the same bargain `goal` makes.
    """
    return _parse_string(text, "recap")


def parse_clarify_about(text: str) -> str | None:
    """The column a clarification is about, if the model named one.

    The chips offered with a clarification are the real values of whichever
    column the doubt is about, and until now the only way to find that column
    was to look for its name inside the question the user is shown -- which
    meant the feature could only work when the question leaked a schema name.
    Asking for the column in its own key separates the two: the prose stays
    written for a person, and the lookup gets the identifier it needs.

    Never public. redact.public_response does not carry it, and nothing
    renders it.
    """
    return _parse_string(text, "about")


def parse_group(text: str) -> bool:
    """Whether the model asked for this answer's rows to be collected.

    A grouping is a claim about how an answer reads, and only the question and
    the answer together decide that -- which is why the table-level nomination
    in column_hierarchy.yaml could not: it fires on every answer off that
    table, including the ones nobody asked to have grouped. The file still
    says WHICH columns may head a group and which are totals, so the model
    never sees or names a column; it only says whether to use them here.

    False unless the model said otherwise. A plain list is the normal answer,
    and an absent key is the model not asking for anything.
    """
    for obj in _json_objects(text):
        value = obj.get("group")
        if isinstance(value, bool):
            return value
    return False


def parse_options(text: str) -> list[str]:
    """The readings the model offered to choose between.

    Only the model can produce these. When it says a question has five
    possible meanings, those meanings exist nowhere in the schema -- they are
    readings of the sentence, not values in a column -- so the gazetteer has
    nothing to offer and the user is left retyping one of them by hand.
    """
    return _parse_string_list(text, "options")


def parse_next(text: str) -> list[str]:
    """Follow-up questions the model thinks are worth asking next.

    The registry can only offer what the schema affords -- narrow by a status,
    group by a column, count the rows -- and after "which departments are
    performing poorly" it duly offers "Just count them", which answers nothing
    anyone wanted. Relevance needs the question, and only the model has it.
    """
    return _parse_string_list(text, "next")
