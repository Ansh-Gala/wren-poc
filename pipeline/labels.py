"""Readable headings for database column names.

Presentation only. The SQL, the result keys and the column names the database
returned are all untouched -- this produces a parallel list of labels, so
anything reading `columns` still sees exactly what PostgreSQL said.

Generic by construction: split on underscores, title-case the words. There is
no per-column table, and adding one would be the wrong shape -- a generated
alias such as `avg_delay_days` has never appeared in any registry and still
has to render as "Avg Delay Days".
"""

from __future__ import annotations

import re

# Words the schema itself writes in capitals, and which title case makes
# unreadable ("Task Sla Status"). Deliberately short: every entry is a token
# that occurs in a real column name and is capitalised in that column's own
# description in metadata/schema_description.yaml.
#
# Not included, on purpose: id, ref, qty, desc, dept. Those read correctly in
# title case -- "Business Object Ref Id" -- and expanding them would fight the
# convention rather than follow it.
_ACRONYMS = {
    "sla": "SLA",      # "SLA status", "allowed task duration / SLA buffer"
    "bo": "BO",        # "Also known as Initiative, Order, or BO"
    "moq": "MOQ",      # "Minimum order quantity attribute"
    "csbd": "CSBD",    # "CSBD date attribute"
    "pi": "PI",        # "PI date attribute"
    "won": "WON",      # "MCode/WON number attribute"
}

# Split on underscores and on runs of whitespace, so a column that already
# arrived with spaces (a quoted alias) is handled by the same path.
_SEPARATORS = re.compile(r"[_\s]+")


def column_label(name: str | None) -> str:
    """One column name as a heading. ``business_object_ref_id`` -> ``Business Object Ref Id``."""
    if not name:
        return ""
    words = [w for w in _SEPARATORS.split(str(name).strip()) if w]
    return " ".join(_ACRONYMS.get(w.lower(), w[:1].upper() + w[1:]) for w in words)


def column_labels(names: list[str] | None) -> list[str]:
    """Headings for a result set, positionally aligned with ``names``.

    Length and order are preserved even where a name is empty, because the UI
    zips this against the column list to build the header row.
    """
    return [column_label(name) for name in (names or [])]


def with_column_labels(result):
    """A result dict with readable headings added beside its column names.

    Additive, never a replacement: `columns` keeps exactly what PostgreSQL
    said, so the state reader and the debug pane still see the real names.
    Anything that is not a dict passes through -- a clarification has no
    result, and inventing an empty table for it would put a header row under
    a sentence.
    """
    if not isinstance(result, dict):
        return result
    return {**result, "column_labels": column_labels(result.get("columns"))}


def with_presentation(result, tables):
    """A result dict with display order and hidden columns added.

    Additive in the same way as with_column_labels, and for the same reason:
    `columns` and `rows` keep exactly what PostgreSQL said, so the state
    reader and the debug pane are unaffected. Anything that is not a dict
    passes through -- a clarification has no result, and inventing an empty
    table for it would put a header row under a sentence.
    """
    if not isinstance(result, dict):
        return result
    from pipeline.column_order import presentation

    shape = presentation(result.get("columns"), tables)
    return {**result, "column_order": shape["order"],
            "hidden_columns": shape["hidden"]}
