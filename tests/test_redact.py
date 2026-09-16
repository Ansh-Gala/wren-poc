"""What a turn is allowed to tell the browser.

Two separate promises. A failed query must not report the table and column it
failed on, and a normal answer must not carry the SQL, the schema names or the
diagnostics that only a developer wants.

Both are asserted against the sensitive strings themselves rather than against
a field list, because the risk is a field nobody thought about rather than a
field somebody named.
"""

from __future__ import annotations

import json

import pytest

from pipeline.redact import public_response, safe_error

# Real identifiers from this database. Any of these reaching a normal response
# is the leak, whichever field it arrives in.
SENSITIVE = [
    "tms_task_flat", "tms_initiative_flat", "tms_user_flat",
    "task_start_at", "initiative_ref_id", "current_milestone_delay_days",
    "SELECT", "FROM", "WHERE", "JOIN",
    "public", "psycopg", "Traceback",
]


def assert_nothing_sensitive(payload: dict) -> None:
    blob = json.dumps(payload)
    found = [s for s in SENSITIVE if s in blob]
    assert not found, f"leaked {found} in {blob[:400]}"


# ----------------------------------------------------------- safe_error --

def test_a_turn_that_did_not_fail_has_no_error():
    """None in, None out. Inventing a message would banner a good answer."""
    assert safe_error(None) is None
    assert safe_error("") is None


@pytest.mark.parametrize("raw,sqlstate", [
    # The example from the report.
    ('column "task_start_at" of relation "tms_task_flat" does not exist', "42703"),
    ('relation "tms_nowhere_flat" does not exist', "42P01"),
    ("canceling statement due to statement timeout", "57014"),
    ('syntax error at or near "SELCT"', "42601"),
    ("permission denied for table tms_task_flat", "42501"),
    ('cannot delete from view "tms_task_flat"', "55000"),
    # No sqlstate at all -- an error from somewhere other than the driver.
    ("KeyError: 'tms_task_flat'", None),
    ("Traceback (most recent call last):\n  File \"pipeline/lean_runner.py\"", None),
])
def test_a_database_error_never_reaches_the_user(raw, sqlstate):
    message = safe_error(raw, sqlstate)
    assert message
    assert_nothing_sensitive({"error": message})


def test_the_safe_message_still_says_something_useful():
    """Sanitised is not the same as empty."""
    timeout = safe_error("canceling statement due to statement timeout", "57014")
    assert "too long" in timeout.lower()

    missing = safe_error('column "x" does not exist', "42703")
    assert "couldn't find" in missing.lower()
    # Business vocabulary is fine; it is what the user asked in.
    assert "task" in missing.lower()

    readonly = safe_error("permission denied", "42501")
    assert "read" in readonly.lower()


def test_an_unrecognised_sqlstate_still_gets_a_safe_message():
    """The default has to be safe, not passthrough."""
    message = safe_error('deadlock detected on tms_task_flat', "40P01")
    assert_nothing_sensitive({"error": message})
    assert "couldn't process" in message.lower()


# ------------------------------------------------------ public_response --

def full_turn() -> dict:
    """A response with every field a real successful turn carries."""
    return {
        "decision": "new_block",
        "question": "show me the delayed tasks",
        "normalized_question": "show me the delayed tasks",
        "repairs": [],
        "resumed_from": None,
        "preflight_clarified": False,
        "generated_sql": "SELECT task_id, task_start_at FROM tms_task_flat "
                         "WHERE task_sla_status = 'Delayed'",
        "sql_valid": True,
        "execution_success": True,
        "error": None,
        "raw_error": 'column "task_start_at" of relation "tms_task_flat" does not exist',
        "failure_category": "",
        "result": {
            "columns": ["task_id", "task_start_at"],
            "column_labels": ["Task Id", "Task Start At"],
            "rows": [[1, "2026-01-01"]],
            "row_count": 1,
            "truncated": False,
        },
        "semantic_match": None,
        "semantic_issues": ["projection differs on tms_task_flat.task_start_at"],
        "projection_verdict": "ok",
        "result_match": None,
        "schema_grounded": True,
        "hallucinated": False,
        "clarification": None,
        "followup": {"type": "none", "suggestions": []},
        "state": {"entity": None, "tables": ["tms_task_flat"],
                  "filters": {"task_sla_status": "task_sla_status = 'Delayed'"}},
        "state_mutations": ["+ filter task_sla_status = 'Delayed'"],
        "tokens": {"prompt": 10850, "cache_read": 10848, "completion": 90},
        "latency_ms": 6517.0,
        "tool_calls": 0,
        "context_chars": 0,
        "raw_output": '{"sql": "SELECT task_id FROM tms_task_flat"}',
    }


def test_debug_off_leaks_nothing_about_the_database():
    """The whole promise, asserted over the serialised payload."""
    assert_nothing_sensitive(public_response(full_turn()))


@pytest.mark.parametrize("field", [
    "generated_sql", "raw_output", "raw_error", "state", "state_mutations",
    "tokens", "latency_ms", "semantic_issues", "failure_category",
    "schema_grounded", "hallucinated", "sql_valid", "execution_success",
    "decision", "context_chars", "tool_calls", "normalized_question",
])
def test_debug_off_drops_every_diagnostic_field(field):
    assert field not in public_response(full_turn())


def test_debug_off_keeps_what_the_answer_is_made_of():
    out = public_response(full_turn())
    assert out["question"] == "show me the delayed tasks"
    assert out["followup"] == {"type": "none", "suggestions": []}
    assert out["result"]["rows"] == [[1, "2026-01-01"]]
    assert out["result"]["row_count"] == 1


def test_debug_off_sends_labels_but_not_column_names():
    """Readable headings are the presentation; the raw names are metadata."""
    result = public_response(full_turn())["result"]
    assert result["column_labels"] == ["Task Id", "Task Start At"]
    assert "columns" not in result


def test_debug_off_keeps_a_clarification_because_the_model_wrote_it_to_be_read():
    turn = full_turn()
    turn["clarification"] = "Did you mean open tasks or closed ones?"
    assert public_response(turn)["clarification"] == turn["clarification"]


def test_debug_off_carries_the_sanitised_error_not_the_raw_one():
    turn = full_turn()
    turn["error"] = safe_error(turn["raw_error"], "42703")
    out = public_response(turn)
    assert out["error"]
    assert "raw_error" not in out
    assert_nothing_sensitive(out)


def test_a_field_added_later_is_hidden_until_someone_decides_otherwise():
    """The filter is a whitelist, so new diagnostics do not leak by default."""
    turn = full_turn()
    turn["some_new_diagnostic"] = "tms_task_flat internals"
    assert "some_new_diagnostic" not in public_response(turn)


def test_a_turn_with_no_result_is_not_an_error():
    """A clarification has no rows, and must not grow an empty table."""
    turn = full_turn()
    turn["result"] = None
    out = public_response(turn)
    assert out["result"] is None


def test_the_full_response_is_left_alone():
    """public_response must not mutate what it filters -- debug on reuses it."""
    turn = full_turn()
    before = json.dumps(turn)
    public_response(turn)
    assert json.dumps(turn) == before


# ------------------------------------------------- followup suggestions --

def turn_with_suggestions() -> dict:
    turn = full_turn()
    turn["followup"] = {
        "follow_up_required": True,
        "type": "exploration",
        "reason": "useful_next_actions",
        "question": "What would you like to explore next?",
        "suggestions": [
            {"id": "filter_open_task", "label": "Only the open ones",
             "action": {"type": "add_filter", "field": "task_status",
                        "operator": "=", "value": "open"}},
            {"id": "remove_task_sla_status",
             "label": "Remove the task sla status filter",
             "action": {"type": "remove_filter", "field": "task_sla_status"}},
        ],
    }
    return turn


def test_the_chips_survive_debug_off_because_they_are_the_product():
    followup = public_response(turn_with_suggestions())["followup"]
    assert followup["type"] == "exploration"
    assert [s["label"] for s in followup["suggestions"]] == [
        "Only the open ones", "Remove the task sla status filter",
    ]


def test_but_their_plumbing_does_not():
    """`action` names the column it filters on, and `id` is built from it.

    Neither is ever displayed. A chip works by sending its own label as the
    next question, which the follow-up layer already documents as the path
    that keeps one way of building a query.
    """
    followup = public_response(turn_with_suggestions())["followup"]
    for suggestion in followup["suggestions"]:
        assert set(suggestion) == {"label"}
    assert "reason" not in followup
    assert "follow_up_required" not in followup
    assert_nothing_sensitive(public_response(turn_with_suggestions()))


def test_the_identifier_form_of_a_column_never_travels():
    """Prose is allowed, identifiers are not.

    "task sla status" in a chip label is the wording a person reads.
    "task_sla_status" is the name of a column, and the difference is the whole
    line being drawn here.
    """
    blob = json.dumps(public_response(turn_with_suggestions()))
    assert "task_sla_status" not in blob
    assert "task_status" not in blob
    assert "task sla status" in blob


def test_debug_on_keeps_the_actions_so_the_chips_can_pre_apply_state():
    turn = turn_with_suggestions()
    assert turn["followup"]["suggestions"][0]["action"]["field"] == "task_status"


def test_a_turn_with_no_suggestions_still_has_a_followup_shape():
    turn = full_turn()
    turn["followup"] = {"type": "none", "suggestions": []}
    assert public_response(turn)["followup"] == {"type": "none", "suggestions": []}
