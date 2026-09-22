"""What a turn is allowed to tell the browser.

Two jobs, both about the boundary rather than about the pipeline.

``safe_error`` replaces a database error with something a person can act on.
Replacing rather than scrubbing: a raw message names the table and column it
failed on, and any attempt to filter identifiers out of free text will miss a
form nobody anticipated. Discarding the message entirely cannot.

``public_response`` drops every field that exists for debugging. It is a
whitelist, so a field added to the response later is hidden until someone
decides otherwise -- the alternative leaks by default, which is the wrong way
round for a payload carrying SQL and schema names.
"""

from __future__ import annotations

import re
from typing import Any

# Enough of the answer to act on, and no more. The nouns here are business
# vocabulary from the semantic layer's TERMINOLOGY section -- "task",
# "initiative" -- not table or column names.
_GENERIC = ("I couldn't process that request. Please try rephrasing your "
            "question.")

_BY_SQLSTATE = {
    # query_canceled: the statement timeout fired.
    "57014": ("That question took too long to answer. Try narrowing it down -- "
              "a single business unit, or a shorter date range."),
    # undefined_column / undefined_table: the query named something absent.
    "42703": ("I couldn't find the information you asked for. Try asking about "
              "tasks, initiatives, users, departments or roles."),
    "42P01": ("I couldn't find the information you asked for. Try asking about "
              "tasks, initiatives, users, departments or roles."),
    # syntax_error, and the read-only refusals.
    "42601": _GENERIC,
    "42501": ("I can only read data, so I can't make that change."),
    "55000": ("I can only read data, so I can't make that change."),
}

# Fields a normal answer may carry. Everything absent from this set is
# diagnostic and reaches the browser only with debug on.
_PUBLIC_FIELDS = frozenset({
    "question",        # what they typed, echoed back
    "clarification",   # the model's own words, written to be read
    "followup",        # the suggestion chips
    "result",          # rows, and the readable headings
    "error",           # sanitised by safe_error before it gets here
})

# Inside ``result``, the same distinction. ``columns`` holds raw database
# column names, so only the labels travel when debug is off.
#
# column_order and hidden_columns are public deliberately. They are lists of
# integer positions into the result, so they name nothing: no column, no table,
# no SQL. They are strictly less revealing than column_labels, which is already
# here and is derived from the column names themselves. And they have to travel
# with a normal answer, because debug off is the mode the grid actually runs in
# -- withholding them would leave the presentation metadata reaching only the
# people who least need it.
#
# initiative and colours are public for the same reason and on the same terms.
# `initiative` is three integer positions into the result; `colours` maps an
# initiative id -- a number the reader is about to be shown anyway, and which
# the details dialog takes -- to a CSS class code such as "a_bl". Neither
# carries a column name, a table name or any SQL. Without them here the grid
# would draw no colour bar and open no dialog when debug is off, which is the
# mode it actually runs in: exactly how the column hierarchy shipped inert.
_PUBLIC_RESULT_FIELDS = frozenset({"column_labels", "rows", "row_count", "truncated",
                                   "column_order", "hidden_columns",
                                   "initiative", "colours", "grouping"})

# The suggestion chips stay -- they are the product, not a diagnostic -- but
# their plumbing does not. `action` carries the column it filters on and `id`
# is built from it, and neither is ever displayed: a chip works by sending its
# own label as the next question, which is the path the follow-up layer
# already documents as the one that keeps a single way for a query to be
# built. What remains is the wording, which is prose rather than an
# identifier.
_PUBLIC_FOLLOWUP_FIELDS = frozenset({"type", "question", "suggestions"})
_PUBLIC_SUGGESTION_FIELDS = frozenset({"label"})

# Text that gives the game away: an identifier, or a query.
#
# Identifiers in this schema are snake_case -- tms_task_flat, task_sla_status,
# is_initiative_delayed -- and prose written for a person is not. Testing the
# shape rather than a list of known names is the stronger check: it catches a
# column this file has never heard of, and a name the model invented, neither
# of which a whitelist would.
#
# Matching against the schema's own names was tried and is wrong here. Some
# columns are single ordinary words -- status, department, role, season -- and
# a clarification is *supposed* to say "which department did you mean?". A
# name-based scan would drop nearly every question worth asking.
_TELLS = (
    # An underscore joining two word characters: snake_case, so an identifier.
    re.compile(r"\b[A-Za-z][A-Za-z0-9]*(?:_[A-Za-z0-9]+)+\b"),
    # A query, or a reference to one. Upper case deliberately: "select" is an
    # ordinary verb, SELECT is a keyword.
    re.compile(r"\b(?:SELECT|FROM|WHERE|JOIN|GROUP BY|ORDER BY)\b"),
    re.compile(r"\bSQL\b", re.IGNORECASE),
    # A column's type is a database detail like any other, and "what type
    # is that field" is a question a person can ask in ordinary words.
    # Only the unmistakable ones: "text", "date" and "time" are English
    # before they are types, and blocking those would cost every sentence
    # worth reading.
    re.compile(r"\b(?:VARCHAR|NVARCHAR|BIGINT|SMALLINT|TINYINT|INTEGER|BOOLEAN|TIMESTAMP|DATETIME|NUMERIC|SERIAL|JSONB|UUID)\b", re.IGNORECASE),
)


def names_a_database_object(text: str | None) -> bool:
    """Whether a piece of user-facing text gives a database detail away.

    Shared, so the boundary and the chip builder cannot start disagreeing
    about what counts. Shape rather than a list of real names: a list would
    miss a column this file has never heard of, and it would also drop every
    sentence containing "status" or "department", which are columns and
    ordinary English at the same time.
    """
    flat = " ".join(str(text or "").split())
    return bool(flat) and any(t.search(flat) for t in _TELLS)

# What a clarification becomes when it trips a tell.
#
# Replaced rather than dropped, which is where this parts company with the
# explanation guard on the PHP side. An explanation is a nicety and a turn
# reads fine without one. A clarification is the entire turn: drop it and the
# user is left with a set of chips under a blank space, with nothing saying
# what is being asked. The chips carry the actual choices, so a generic
# opening still leaves a question that can be answered.
_CLARIFY_FALLBACK = ("Could you tell me a bit more about what you are looking "
                     "for?")


def safe_error(error: str | None, sqlstate: str | None = None) -> str | None:
    """A database error as something worth showing a user.

    ``None`` in, ``None`` out: a turn that did not fail has no error, and
    inventing one would put a banner on a successful answer.
    """
    if not error:
        return None
    return _BY_SQLSTATE.get((sqlstate or "").strip(), _GENERIC)


def safe_clarification(text: str | None) -> str | None:
    """The model's question, if it is fit to show.

    ``None`` in, ``None`` out: most turns are answers and have no
    clarification, and inventing one would ask a question nobody meant.
    """
    if text is None or not str(text).strip():
        return None
    body = str(text).strip()
    return _CLARIFY_FALLBACK if names_a_database_object(body) else body


def public_response(response: dict[str, Any]) -> dict[str, Any]:
    """The debug-off view of a turn.

    Filtered here rather than hidden in the page, because a field the browser
    receives has already left the server -- hiding it in the DOM still ships
    the SQL to whoever opens the network tab.
    """
    out = {k: v for k, v in response.items() if k in _PUBLIC_FIELDS}

    # Whitelisting the field is not enough: its contents are model prose, and
    # the model has the whole schema in front of it.
    if "clarification" in out:
        out["clarification"] = safe_clarification(out["clarification"])

    result = response.get("result")
    if isinstance(result, dict):
        out["result"] = {k: v for k, v in result.items() if k in _PUBLIC_RESULT_FIELDS}

    followup = response.get("followup")
    if isinstance(followup, dict):
        trimmed = {k: v for k, v in followup.items() if k in _PUBLIC_FOLLOWUP_FIELDS}
        if trimmed.get("type") == "clarification":
            trimmed["question"] = safe_clarification(trimmed.get("question")) or ""
        trimmed["suggestions"] = [
            {k: v for k, v in s.items() if k in _PUBLIC_SUGGESTION_FIELDS}
            for s in (followup.get("suggestions") or [])
            if isinstance(s, dict)
        ]
        out["followup"] = trimmed

    return out
