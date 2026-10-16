"""Saved chats: what a row holds, and how a reopened chat reads back.

No database here: the SQL was checked against the live tables, read-only. These
pin the rules the store shares with Drupal's ConversationStore and TurnOutcome.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from pipeline import chat_store as cs
from pipeline.context import ConversationState
from pipeline.lean_runner import TurnResult

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))
import scripts.serve_api as api  # noqa: E402


def _turn(**fields) -> TurnResult:
    r = TurnResult(turn_id="t.0", conversation_id="t", turn_index=0,
                   category="runtime", question="q")
    for name, value in fields.items():
        setattr(r, name, value)
    return r


# ----------------------------------------------------------- turn outcome --

@pytest.mark.parametrize("fields,status", [
    ({"clarification": "Which one?"}, "clarification"),
    ({"preflight_clarified": True}, "clarification"),
    ({"generated_sql": None, "error": "boom"}, "llm_error"),
    ({"generated_sql": None, "timed_out": True}, "llm_error"),
    ({"generated_sql": None}, "no_sql"),
    ({"generated_sql": "DELETE", "sql_valid": False}, "unsafe_sql"),
    ({"generated_sql": "SELECT 1", "sql_valid": True}, "execution_failed"),
    ({"generated_sql": "SELECT 1", "sql_valid": True, "execution_success": True,
      "error": "a warning"}, "success"),
])
def test_the_status_drupal_would_record(fields, status):
    assert cs.turn_status(_turn(**fields)) == status


def test_what_the_person_saw():
    assert cs.response_type("success") == "sql_result"
    assert cs.response_type("clarification") == "clarification"
    assert cs.response_type("unsafe_sql") == "error"


def test_cache_reads_cost_a_tenth():
    r = _turn(prompt_tokens=20000, cache_read_tokens=18000, completion_tokens=200)
    assert cs.effective_tokens(r) == 20000 - 18000 + 1800 + 200


def test_effective_tokens_are_never_negative():
    assert cs.effective_tokens(_turn(prompt_tokens=0, cache_read_tokens=500)) == 0


# ------------------------------------------------------------- identifiers --

@pytest.mark.parametrize("raw,safe", [
    ("react-k3j-9x", "react-k3j-9x"),
    ("", "default"), (None, "default"),
    ("a b/c;d", "a_b_c_d"),
    ("x" * 80, "x" * 64),
])
def test_a_session_id_is_bounded_and_plain(raw, safe):
    assert cs.safe_session_id(raw) == safe


def test_a_title_is_the_question_clipped_at_a_word():
    long = "show me " + "delayed tasks in the sales department " * 5
    title = cs.title_from(long)
    assert len(title) <= cs.TITLE_MAX + 1 and title.endswith("…")
    assert not title[:-1].endswith(" ")
    assert cs.title_from("  open   tasks ") == "open tasks"


# ---------------------------------------------------------------- the row --

def test_the_state_is_stored_with_drupals_keys():
    """ConversationState::toArray's keys, so either side reads the other."""
    keys = list(cs.state_array(ConversationState()))
    assert keys == ["active_goal", "active_subject", "active_entity", "active_tables",
                    "active_filters", "active_grouping", "active_sorting", "active_limit",
                    "last_intent", "previous_sql", "previous_result_summary",
                    "turns_in_block", "pending_clarification", "pending_question",
                    "awaiting_answer_to", "rolling_recap", "recent_questions"]


def test_metadata_keeps_the_shape_of_an_answer_never_its_rows():
    r = _turn(actual_result={"columns": ["secret_col"], "rows": [[1], [2]],
                             "row_count": 2, "truncated": False},
              llm_mode="cli", llm_provider="claude-cli", context_reset=True,
              normalized_question="open tasks", raw_output='{"sql": "SELECT 1"}')
    meta = json.loads(cs.metadata_for(r, "opne tasks", ConversationState()))
    assert meta["result"] == {"row_count": 2, "truncated": False}
    assert "secret_col" not in json.dumps(meta["result"])
    assert meta["llm"] == {"mode": "cli", "provider": "claude-cli", "model": None}
    assert meta["pipeline"]["context_reset"] is True
    assert meta["pipeline"]["normalized_question"] == "open tasks"
    assert meta["state"]["rolling_recap"] is None
    assert meta["raw_output"] == '{"sql": "SELECT 1"}'


def test_no_query_is_none_rows_not_zero():
    meta = json.loads(cs.metadata_for(_turn(actual_result={}), "q"))
    assert meta["result"]["row_count"] is None


def test_an_oversized_row_sheds_the_raw_reply_before_the_state():
    r = _turn(raw_output="x" * 50000)
    meta = json.loads(cs.metadata_for(r, "q", ConversationState()))
    assert len(json.dumps(meta)) <= cs.METADATA_MAX
    assert "state" in meta, "the state is shed last"


def test_step_timings_carry_the_start_and_each_step():
    r = _turn(turn_started=1_760_000_000.5, latency_ms=2500.0, llm_ms=1800.0,
              llm_wall_ms=2000.0, db_ms=40.0)
    timings = json.loads(cs.step_timings(r))
    assert timings["total_ms"] == 2500.0
    assert timings["started"] and timings["ended"]
    assert timings["steps"]["llm"]["ms"] == 2000.0
    assert timings["steps"]["sql"]["ms"] == 40.0


def test_without_a_login_nothing_is_stored_or_read():
    settings = SimpleNamespace(history_db_user="", chat_table_prefix="vf_")
    store = cs.ChatStore(settings, 7)
    assert not store.enabled
    assert store.load("s")["chat_id"] is None
    assert store.save("s", "q") is None
    store.record_turn(1, 0, "q", _turn(), {})    # no error, no connection


def test_nobody_owns_nothing():
    settings = SimpleNamespace(history_db_user="writer", chat_table_prefix="vf_")
    assert not cs.ChatStore(settings, 0).enabled


# ------------------------------------------------------- reading it back --

ROW = {"sequence_number": 1, "question": "open tasks", "status": "success",
       "response_type": "sql_result", "llm_response": "The open tasks.",
       "generated_sql": "SELECT task_id FROM tms_task_flat", "created_at": 1_760_000_000,
       "step_timings": '{"total_ms": 1}',
       "metadata": {"result": {"row_count": 3, "truncated": False},
                    "followup": {"type": "clarification", "question": "Which?",
                                 "suggestions": [{"label": "Sales", "ref": "n:0"}]}}}
CHAT = {"id": 9, "session_id": "react-x", "title": "", "created_at": 1_760_000_000,
        "updated_at": 1_760_000_100}


def test_a_reopened_chat_has_no_rows_and_no_sql():
    out = api.present_chat({"chat": CHAT, "turns": [ROW]}, debug=False)
    turn = out["turns"][0]
    assert turn["result"] == {"row_count": 3, "truncated": False, "rows": []}
    assert turn["explanation"] == "The open tasks."
    assert "generated_sql" not in turn and "metadata" not in turn
    assert out["chat"]["title"] == "Untitled chat"
    assert out["chat"]["turn_count"] == 1


def test_a_replayed_chip_cannot_answer_anything():
    """A ref ties a chip to an outstanding clarification; a transcript has none."""
    turn = api.present_chat({"chat": CHAT, "turns": [ROW]}, debug=False)["turns"][0]
    assert turn["followup"]["suggestions"] == [{"label": "Sales"}]


def test_debug_adds_the_sql_and_the_timings():
    turn = api.present_chat({"chat": CHAT, "turns": [ROW]}, debug=True)["turns"][0]
    assert turn["generated_sql"].startswith("SELECT")
    assert turn["step_timings"] == {"total_ms": 1}


def test_a_failed_turn_shows_its_stored_error():
    row = {**ROW, "status": "execution_failed", "llm_response": "I couldn't find that."}
    turn = api.present_chat({"chat": CHAT, "turns": [row]}, debug=False)["turns"][0]
    assert turn["error"] == "I couldn't find that." and turn["explanation"] is None


@pytest.mark.parametrize("value,cell", [
    ("=SUM(A1)", "'=SUM(A1)"), ("@x", "'@x"), ("-5", "-5"), ("-", "'-"),
    ("AR_YD_Suiting", "AR_YD_Suiting"), (None, ""), (True, "true"), (3, "3"),
])
def test_csv_cells_as_drupal_writes_them(value, cell):
    assert api.csv_cell(value) == cell
