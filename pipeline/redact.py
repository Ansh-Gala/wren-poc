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

from typing import Any

# Enough of the answer to act on, and no more. The nouns here are business
# vocabulary from the semantic layer's TERMINOLOGY section -- "task",
# "business object" -- not table or column names.
_GENERIC = ("I couldn't process that request. Please try rephrasing your "
            "question.")

_BY_SQLSTATE = {
    # query_canceled: the statement timeout fired.
    "57014": ("That question took too long to answer. Try narrowing it down -- "
              "a single business unit, or a shorter date range."),
    # undefined_column / undefined_table: the query named something absent.
    "42703": ("I couldn't find the information you asked for. Try asking about "
              "tasks, business objects, users, departments or roles."),
    "42P01": ("I couldn't find the information you asked for. Try asking about "
              "tasks, business objects, users, departments or roles."),
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
_PUBLIC_RESULT_FIELDS = frozenset({"column_labels", "rows", "row_count", "truncated",
                                   "column_order", "hidden_columns"})

# The suggestion chips stay -- they are the product, not a diagnostic -- but
# their plumbing does not. `action` carries the column it filters on and `id`
# is built from it, and neither is ever displayed: a chip works by sending its
# own label as the next question, which is the path the follow-up layer
# already documents as the one that keeps a single way for a query to be
# built. What remains is the wording, which is prose rather than an
# identifier.
_PUBLIC_FOLLOWUP_FIELDS = frozenset({"type", "question", "suggestions"})
_PUBLIC_SUGGESTION_FIELDS = frozenset({"label"})


def safe_error(error: str | None, sqlstate: str | None = None) -> str | None:
    """A database error as something worth showing a user.

    ``None`` in, ``None`` out: a turn that did not fail has no error, and
    inventing one would put a banner on a successful answer.
    """
    if not error:
        return None
    return _BY_SQLSTATE.get((sqlstate or "").strip(), _GENERIC)


def public_response(response: dict[str, Any]) -> dict[str, Any]:
    """The debug-off view of a turn.

    Filtered here rather than hidden in the page, because a field the browser
    receives has already left the server -- hiding it in the DOM still ships
    the SQL to whoever opens the network tab.
    """
    out = {k: v for k, v in response.items() if k in _PUBLIC_FIELDS}

    result = response.get("result")
    if isinstance(result, dict):
        out["result"] = {k: v for k, v in result.items() if k in _PUBLIC_RESULT_FIELDS}

    followup = response.get("followup")
    if isinstance(followup, dict):
        trimmed = {k: v for k, v in followup.items() if k in _PUBLIC_FOLLOWUP_FIELDS}
        trimmed["suggestions"] = [
            {k: v for k, v in s.items() if k in _PUBLIC_SUGGESTION_FIELDS}
            for s in (followup.get("suggestions") or [])
            if isinstance(s, dict)
        ]
        out["followup"] = trimmed

    return out
