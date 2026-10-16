"""The constraints in force, as pills the reader can see and drop.

Ported from the Drupal port's ChatRuntime: contextPills, dropByRef, pillRef
and pillLabel.

The model never sees the state, so taking a filter off the state changes
nothing it reads. A dropped filter is therefore also recorded in
ConversationState.dropped_filters, which the context block names for that one
turn; left to the question's wording, the open-by-default rule put a dropped
"task_status = 'open'" back in 4 of 10 runs.
"""

from __future__ import annotations

import hashlib
import re

from pipeline.context import ConversationState
from pipeline.labels import column_phrase
from pipeline.redact import names_a_database_object

# "tms_task_flat." and the like: stripped first, or a table name would leak
# into a public label.
_QUALIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\.")


def context_pills(state: ConversationState) -> list[dict]:
    """The subject and the filters in force, each with a handle to drop it."""
    pills = []
    subject_column = None
    if state.active_subject is not None:
        subject_column = state.active_subject.get("column")
        pills.append({"ref": pill_ref("subject"),
                      "label": state.active_subject.get("label"),
                      "kind": "subject"})
    for column, predicate in state.active_filters.items():
        # The subject came from this filter; don't show it twice.
        if subject_column is not None and column == subject_column:
            continue
        pills.append({"ref": pill_ref(column),
                      "label": pill_label(column, predicate),
                      "kind": "filter"})
    return pills


def drop_by_ref(state: ConversationState, ref: str) -> bool:
    """Take one constraint off the state, given the handle a pill sent back.

    Whether anything matched; a stale ref matches nothing.
    """
    if state.active_subject is not None and ref == pill_ref("subject"):
        column = state.active_subject.get("column")
        if column is not None and column in state.active_filters:
            state.dropped_filters.append(state.active_filters[column])
        state.active_subject = None
        return True
    for column in list(state.active_filters):
        if ref == pill_ref(column):
            state.dropped_filters.append(state.active_filters[column])
            del state.active_filters[column]
            return True
    return False


def pill_ref(key: str) -> str:
    """A handle for one pill, naming nothing: stable across requests without
    telling the browser which column it stands for."""
    return hashlib.sha256(f"vf-pill:{key}".encode("utf-8")).hexdigest()[:10]


def pill_label(column: str, predicate: str) -> str:
    """A predicate in the words the reader uses for that column.

    The label is substituted into the existing predicate rather than rebuilt,
    so it cannot misstate what is in force. Anything still shaped like an
    identifier -- a column-to-column compare, say -- falls back to the
    column's own label rather than leak a name.
    """
    label = _QUALIFIER.sub("", str(predicate))
    label = label.replace(column, column_phrase(column))
    label = label.replace("'", "").strip()
    return column_phrase(column) if names_a_database_object(label) else label
