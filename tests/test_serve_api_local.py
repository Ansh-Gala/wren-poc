"""The console is a tool for one person: what it keeps to this machine.

The FastAPI app through its test client, a stub runtime, no database and no
model.
"""

from __future__ import annotations

import json
import sys
import threading
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

# serve_api imports _bootstrap, which sits beside it.
SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import scripts.serve_api as api  # noqa: E402
from pipeline.run_access import RunNotAllowed, user_id_from  # noqa: E402

LEAKY = 'relation "tms_secret_table" does not exist at character 15'


class StubRuntime:
    """Records what it was asked; fails when told to. Authorizes with the
    real user_id rules, and lets user 7 run and nobody else."""

    def __init__(self):
        self.payloads: list[dict] = []
        self.users: list[int] = []
        self.fail = False
        self.settings = SimpleNamespace(stream_answers=True)

    def authorize(self, payload):
        user_id = user_id_from(payload.get("user_id"))
        if user_id != 7:
            raise RunNotAllowed("You do not have permission to ask the chatbot.")
        return user_id

    def ask(self, payload, user_id, on_rows=None):
        self.payloads.append(dict(payload))
        self.users.append(user_id)
        if self.fail:
            raise RuntimeError(LEAKY)
        return {"question": payload.get("question"), "debug": payload.get("debug")}


@pytest.fixture
def server():
    """The app on this machine: the test client's address is loopback."""
    runtime = StubRuntime()
    api.app.state.runtime = runtime
    api.SESSIONS.clear()
    yield TestClient(api.app, client=("127.0.0.1", 50000)), runtime


def _post(client, path, body):
    response = client.post(path, json=body)
    return response.status_code, dict(response.headers), response.text


ME = {"user_id": 7}


def test_a_failed_turn_says_something_general(server):
    client, runtime = server
    runtime.fail = True
    status, _, body = _post(client, "/ask", {**ME, "question": "anything"})
    assert status == 500
    assert "tms_secret_table" not in body and "RuntimeError" not in body
    assert json.loads(body)["error"].startswith("I couldn't process that request")


def test_a_failed_streamed_turn_says_something_general(server):
    client, runtime = server
    runtime.fail = True
    _, _, body = _post(client, "/ask/stream", {**ME, "question": "anything"})
    assert "event: error" in body
    assert "tms_secret_table" not in body and "RuntimeError" not in body


def test_no_web_page_may_read_the_answers(server):
    client, _ = server
    _, headers, _ = _post(client, "/ask", {**ME, "question": "anything"})
    assert not any(name.lower().startswith("access-control") for name in headers)


def test_this_machine_keeps_debug(server):
    client, runtime = server
    _post(client, "/ask", {**ME, "question": "anything", "debug": True})
    assert runtime.payloads[-1]["debug"] is True
    status, _, _ = _post(client, "/debug", {**ME, "session_id": "s"})
    assert status == 200


def test_another_machine_gets_neither_debug_nor_the_debug_log(server, monkeypatch):
    client, runtime = server
    monkeypatch.setattr(api, "_local_client", lambda address: False)

    status, _, _ = _post(client, "/debug", {**ME, "session_id": "s"})
    assert status == 403

    _post(client, "/ask", {**ME, "question": "anything", "debug": True})
    assert runtime.payloads[-1]["debug"] is False
    _post(client, "/ask/stream", {**ME, "question": "anything", "debug": True})
    assert runtime.payloads[-1]["debug"] is False


@pytest.mark.parametrize("address,local", [
    ("127.0.0.1", True), ("::1", True), ("::ffff:127.0.0.1", True),
    ("192.168.1.20", False), ("10.0.0.5", False),
])
def test_what_counts_as_this_machine(address, local):
    assert api._local_client(address) is local


def test_unknown_paths_answer_in_the_servers_shape(server):
    client, _ = server
    assert client.get("/../scripts/serve_api.py").status_code == 404
    response = client.put("/ask")
    assert response.status_code == 405 and "error" in response.json()


# ------------------------------------------------- user_id and run access --

@pytest.mark.parametrize("path", ["/ask", "/ask/stream"])
@pytest.mark.parametrize("user_id,code", [
    (None, "user_id_required"), ("", "user_id_required"),
    ("abc", "user_id_invalid"), (-3, "user_id_invalid"), (0, "user_id_invalid"),
    (True, "user_id_invalid"), (1.5, "user_id_invalid"),
])
def test_a_missing_or_malformed_user_id_is_refused_before_anything_runs(server, path, user_id, code):
    client, runtime = server
    body = {"question": "anything"}
    if user_id is not None:
        body["user_id"] = user_id
    status, _, text = _post(client, path, body)
    assert status == 400 and json.loads(text)["code"] == code
    assert runtime.payloads == [], "no default user is put in its place"


@pytest.mark.parametrize("path", ["/ask", "/ask/stream"])
def test_a_user_without_a_run_role_is_refused_before_anything_runs(server, path):
    client, runtime = server
    status, _, text = _post(client, path, {"user_id": 8, "question": "anything"})
    assert status == 403 and json.loads(text)["code"] == "run_not_allowed"
    assert runtime.payloads == []


def test_the_turn_runs_for_the_user_the_request_names(server):
    client, runtime = server
    _post(client, "/ask", {"user_id": "7", "question": "anything"})
    assert runtime.users == [7]


def test_saved_chats_need_a_user_id_and_the_csv_needs_a_run_role(server, monkeypatch):
    client, runtime = server
    runtime.settings = SimpleNamespace(history_db_name="", history_db_user="",
                                       chat_table_prefix="py_", run_roles=("ticket_owner",))
    assert client.get("/chats").json()["code"] == "user_id_required"
    from pipeline.metadata import profile

    assert client.get("/chats?user_id=7").json() == {
        "chats": [], "total": 0, "welcome": profile().welcome()}

    import pipeline.run_access as access
    monkeypatch.setattr(access, "user_roles", lambda s, uid: frozenset({"authenticated"}))
    refused = client.get("/chats/1/turns/1/csv?user_id=7")
    assert refused.status_code == 403


# ------------------------------------------------------- the answer's shape --

from types import SimpleNamespace  # noqa: E402

from pipeline.context_pills import pill_ref  # noqa: E402
from pipeline.followup import FollowUp, Suggestion  # noqa: E402
from pipeline.lean_runner import TurnResult  # noqa: E402

NOTE = "This data is not updated in real time."
SETTINGS = SimpleNamespace(freshness_tables=("vf_report_task_summary",),
                           freshness_message=NOTE, history_db_name="", history_db_user="",
                           chat_table_prefix="vf_", monthly_token_limit=0)


def _turn(**fields) -> TurnResult:
    r = TurnResult(turn_id="t.0", conversation_id="t", turn_index=0,
                   category="runtime", question="q")
    for name, value in fields.items():
        setattr(r, name, value)
    return r


def _rows(n: int) -> dict:
    return {"columns": ["n"], "rows": [[i] for i in range(n)], "row_count": n,
            "truncated": False}


def test_the_browser_gets_200_rows_and_the_whole_count():
    full = api.to_response(_turn(actual_result=_rows(250)), "q", {}, {}, SETTINGS)
    assert len(full["result"]["rows"]) == 200
    assert full["result"]["row_count"] == 250
    assert full["result"]["truncated"] is True


def test_the_explanation_travels_only_with_an_answer():
    ok = api.to_response(_turn(explanation="The open tasks."), "q", {}, {}, SETTINGS)
    failed = api.to_response(_turn(explanation="The open tasks.", error="boom"),
                             "q", {}, {}, SETTINGS)
    assert ok["explanation"] == "The open tasks."
    assert failed["explanation"] is None, "it would describe an answer that never arrived"


def test_rows_from_a_snapshot_table_carry_the_note():
    snapshot = api.to_response(
        _turn(actual_result=_rows(3), generated_sql="SELECT * FROM vf_report_task_summary"),
        "q", {}, {}, SETTINGS)
    live = api.to_response(
        _turn(actual_result=_rows(3), generated_sql="SELECT * FROM tms_task_flat"),
        "q", {}, {}, SETTINGS)
    assert snapshot["result"]["freshness"] == NOTE
    assert "freshness" not in live["result"]


def test_the_pills_are_passed_through():
    pills = [{"ref": "x", "label": "task status = open", "kind": "filter"}]
    assert api.to_response(_turn(), "q", {}, {}, SETTINGS, pills)["context"] == pills
    assert api.to_response(_turn(), "q", {}, {}, SETTINGS)["context"] == []


@pytest.fixture
def runtime(monkeypatch):
    """The real Runtime.ask, with run_turn faked to record what it was asked."""
    asked: list[str] = []

    def fake_run_turn(turn, *args, **kwargs):
        asked.append(turn.question)
        return _turn(question=turn.question)

    monkeypatch.setattr(api, "run_turn", fake_run_turn)
    monkeypatch.setattr(api, "resolve_identity", lambda settings, user_id: None)
    api.SESSIONS.clear()
    rt = api.Runtime.__new__(api.Runtime)
    rt.settings, rt.gazetteer, rt.mcp_config_path = SETTINGS, [], None
    rt.privacy, rt.context_mode, rt.log_path = "strict", "state", None
    return rt, asked


def test_dropping_a_pill_asks_the_goal_again_without_it(runtime):
    rt, asked = runtime
    state = api.conversation_for("drop", 7).state
    state.active_goal = "open tasks in Sales"
    state.active_filters = {"task_status": "task_status = 'open'"}

    rt.ask({"session_id": "drop", "drop_ref": pill_ref("task_status")}, 7)

    assert asked == ["open tasks in Sales"]
    assert "task_status" not in state.active_filters


def test_a_drop_with_nothing_to_ask_is_refused(runtime):
    rt, _ = runtime
    with pytest.raises(ValueError):
        rt.ask({"session_id": "nothing", "drop_ref": "0000000000"}, 7)


def test_a_chip_ref_asks_the_reading_it_was_offered_for(runtime):
    rt, asked = runtime
    state = api.conversation_for("chip", 7).state
    state.pending_clarification = FollowUp(
        type="clarification", reason="ambiguous_interpretation", question="Which one?",
        suggestions=[Suggestion(id="a", label="Delayed open tasks", ref="n1:0")])

    rt.ask({"session_id": "chip", "question": "the first one", "option_ref": "n1:0"}, 7)
    rt.ask({"session_id": "chip", "question": "typed text", "option_ref": "stale:9"}, 7)

    assert asked == ["Delayed open tasks", "typed text"]


# ------------------------------------------------------------------ charts --

BY_DEPT = {"columns": ["department", "n"], "rows": [["Sales", "3"], ["Design", "5"]],
           "row_count": 2, "truncated": False}
CHART = {"type": "groupedColumn", "category": "department", "values": ["n"]}


def test_a_chart_drawn_from_the_rows_shown():
    full = api.to_response(_turn(actual_result=BY_DEPT, execution_success=True, chart=CHART,
                                 generated_sql="SELECT 1"), "q", {}, {}, SETTINGS)
    assert full["result"]["chart"]["rows"] == [["Sales", 3], ["Design", 5]]
    assert full["chart_reason"] == "ok" and "chart_note" not in full["result"]


def test_a_chart_query_that_failed_draws_nothing_and_says_so():
    full = api.to_response(_turn(actual_result=BY_DEPT, execution_success=True,
                                 chart={**CHART, "sql": "SELECT 2"}, chart_error="timeout"),
                           "q", {}, {}, SETTINGS)
    assert "chart" not in full["result"]
    assert full["chart_reason"] == "chart_sql_timeout"
    assert full["result"]["chart_note"].startswith("No chart: the numbers")


def test_a_chart_query_draws_from_its_own_rows():
    own = {"columns": ["department", "n"], "rows": [["All", "8"]], "row_count": 1,
           "truncated": False, "duration_ms": 3.0}
    full = api.to_response(_turn(actual_result=BY_DEPT, execution_success=True,
                                 chart={**CHART, "sql": "SELECT 2"}, chart_result=own),
                           "q", {}, {}, SETTINGS)
    assert full["result"]["chart"]["rows"] == [["All", 8]]
    assert full["chart_query"] == {"columns": ["department", "n"], "types": [],
                                   "row_count": 1, "duration_ms": 3.0}


def test_a_title_that_names_the_schema_is_dropped():
    full = api.to_response(_turn(actual_result=BY_DEPT, execution_success=True,
                                 chart={**CHART, "title": "count of task_status"}),
                           "q", {}, {}, SETTINGS)
    assert "title" not in full["result"]["chart"]


def test_no_chart_asked_for_says_nothing():
    full = api.to_response(_turn(actual_result=BY_DEPT, execution_success=True), "q", {}, {}, SETTINGS)
    assert full["chart_reason"] is None and "chart" not in full["result"]


def test_the_chart_and_the_download_survive_debug_off():
    full = api.to_response(_turn(actual_result=BY_DEPT, execution_success=True,
                                 chart={**CHART, "colors": {"Sales": "#123456"}}),
                           "q", {}, {}, SETTINGS)
    full["result"]["download"] = {"chat_id": 4, "turn": 2}
    full["result"]["chart"]["internal"] = "kept private"
    public = api.public_response(full)
    assert public["result"]["download"] == {"chat_id": 4, "turn": 2}
    assert set(public["result"]["chart"]) == {"type", "labels", "rows", "colors"}
    assert "chart_reason" not in public and "chart_query" not in public


# ------------------------------------------------- lock, health, streaming --

def test_a_busy_chat_is_waited_for_then_refused(runtime, monkeypatch):
    rt, asked = runtime
    monkeypatch.setattr(api, "LOCK_WAIT_SECONDS", 0.05)
    conversation = api.conversation_for("busy", 7)
    conversation.lock.acquire()
    try:
        with pytest.raises(RuntimeError, match="still being answered"):
            rt.ask({"session_id": "busy", "question": "q"}, 7)
    finally:
        conversation.lock.release()
    assert asked == []
    rt.ask({"session_id": "busy", "question": "q"}, 7)     # released after a turn
    rt.ask({"session_id": "busy", "question": "q"}, 7)
    assert asked == ["q", "q"]


import dataclasses  # noqa: E402

from config.settings import Settings  # noqa: E402
from pipeline.models import QueryResult  # noqa: E402

API = Settings(pg_host="h", pg_port=5432, pg_database="tms", pg_user="u",
               pg_readonly_user="wren_ro", llm_provider="anthropic",
               anthropic_api_key="sk-test", anthropic_model="claude-opus-5-5")


def _health(monkeypatch, settings=API, db_error=None, privileges=("SELECT",)):
    import database.connection as connection
    monkeypatch.setattr(connection, "run_readonly", lambda s, sql: QueryResult(
        columns=[], rows=[], duration_ms=1.0, error=db_error))
    monkeypatch.setattr(connection, "read_only_posture", lambda s: {
        "privileges": list(privileges), "select_only": list(privileges) == ["SELECT"],
        "error": None})
    return api.health(settings)


def test_health_says_what_answers_and_that_all_is_well(monkeypatch):
    assert _health(monkeypatch) == {
        "ok": True, "provider": "api", "api_provider": "anthropic",
        "model": "claude-opus-5-5", "provider_ready": True,
        "database": {"ok": True, "name": "tms", "error": None},
        "read_only_role": {"role": "wren_ro", "privileges": ["SELECT"], "select_only": True},
        "chat_database": {"configured": False, "ok": None, "name": None, "role": None},
        "run_roles": [],
    }


def test_health_fails_on_any_one_check_and_hides_the_database_error(monkeypatch):
    down = _health(monkeypatch, db_error='relation "secret_table" does not exist')
    assert not down["ok"] and down["database"]["error"] == "could not query the database"
    assert not _health(monkeypatch, privileges=("INSERT", "SELECT"))["ok"]
    no_key = _health(monkeypatch, dataclasses.replace(API, anthropic_api_key=""))
    assert not no_key["ok"] and not no_key["provider_ready"]


def _stream(streaming: bool) -> str:
    class Rt:
        settings = SimpleNamespace(stream_answers=streaming)

        def ask(self, payload, user_id, on_rows=None):
            if on_rows is not None:
                on_rows({"sql": "SELECT 1"})
            return {"answer": "done"}

    return "".join(api.stream_events(Rt(), {"question": "q"}, 7))


def test_streaming_off_sends_only_the_answer():
    assert "event: rows" in _stream(True) and "event: answer" in _stream(True)
    assert "event: rows" not in _stream(False) and "event: answer" in _stream(False)


def test_the_console_log_keeps_counts_not_rows(runtime, tmp_path):
    rt, _ = runtime
    rt.log_path, rt.log_lock = tmp_path / "turns.jsonl", threading.Lock()
    rt.record(_turn(actual_result=_rows(3), chart_result=BY_DEPT), "q", {})
    row = json.loads(rt.log_path.read_text(encoding="utf-8"))
    assert row["actual_result"]["rows"] == [] and row["actual_result"]["row_count"] == 3
    assert row["chart_result"]["rows"] == [] and row["chart_result"]["columns"] == ["department", "n"]
