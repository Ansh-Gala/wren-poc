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
    # tms_task_flat.bo_id, the only column with a bare `bo` segment. The
    # schema's own gloss is "Also known as Initiative, Order, or BO"; the
    # heading now says the word the rest of the UI says.
    "bo": "Initiative",
    "moq": "MOQ",      # "Minimum order quantity attribute"
    "csbd": "CSBD",    # "CSBD date attribute"
    "pi": "PI",        # "PI date attribute"
    "won": "WON",      # "MCode/WON number attribute"
}

# Domain terms, applied to the underscore-delimited name before it is split
# into words. A phrase rather than a word, because "business" and "object"
# only mean Initiative together -- a per-word entry mapping "business" would
# turn initiative_id into "Initiative Object Id" and business_unit into
# "Initiative Unit". The database keeps its own names; this is the word the
# people reading the grid use.
_PHRASES = (("business_object", "initiative"),)

# Split on underscores and on runs of whitespace, so a column that already
# arrived with spaces (a quoted alias) is handled by the same path.
_SEPARATORS = re.compile(r"[_\s]+")


def _words(name: str) -> list[str]:
    text = str(name).strip()
    for phrase, replacement in _PHRASES:
        text = text.replace(phrase, replacement)
    return [w for w in _SEPARATORS.split(text) if w]


def column_label(name: str | None) -> str:
    """One column name as a heading. ``initiative_ref_id`` -> ``Initiative Ref Id``."""
    if not name:
        return ""
    return " ".join(_ACRONYMS.get(w.lower(), w[:1].upper() + w[1:])
                    for w in _words(name))


def column_phrase(name: str | None) -> str:
    """One column name as ordinary words, to sit inside a sentence.

    ``initiative_status`` -> ``initiative status``, for "Group by
    initiative status". Shared with the follow-up layer rather than left to
    `column.replace("_", " ")` at each call site: those labels are built from
    column names too, so the domain terms have to be applied in one place or
    the chips and the headings will disagree about what the thing is called.
    """
    if not name:
        return ""
    return " ".join(_words(name))


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
    from pipeline.column_order import grouping, presentation

    shape = presentation(result.get("columns"), tables)
    return {**result, "column_order": shape["order"],
            "hidden_columns": shape["hidden"],
            "grouping": grouping(result.get("columns"), tables)}
