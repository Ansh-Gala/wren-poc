"""The console is a tool for one person: what it keeps to this machine.

A real socket, a stub runtime, no database and no model.
"""

from __future__ import annotations

import json
import sys
import threading
import urllib.error
import urllib.request
from pathlib import Path

import pytest

# serve_api imports _bootstrap, which sits beside it.
SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import scripts.serve_api as api  # noqa: E402

LEAKY = 'relation "tms_secret_table" does not exist at character 15'


class StubRuntime:
    """Records what it was asked; fails when told to."""

    def __init__(self):
        self.payloads: list[dict] = []
        self.fail = False

    def ask(self, payload, on_rows=None):
        self.payloads.append(dict(payload))
        if self.fail:
            raise RuntimeError(LEAKY)
        return {"question": payload.get("question"), "debug": payload.get("debug")}


@pytest.fixture
def server():
    runtime = StubRuntime()
    api.Handler.runtime = runtime
    api.SESSIONS.clear()
    httpd = api.ThreadingHTTPServer(("127.0.0.1", 0), api.Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}", runtime
    httpd.shutdown()
    httpd.server_close()


def _post(base, path, body):
    request = urllib.request.Request(base + path, data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return response.status, dict(response.headers), response.read().decode()
    except urllib.error.HTTPError as exc:
        return exc.code, dict(exc.headers), exc.read().decode()


def test_a_failed_turn_says_something_general(server):
    base, runtime = server
    runtime.fail = True
    status, _, body = _post(base, "/ask", {"question": "anything"})
    assert status == 500
    assert "tms_secret_table" not in body and "RuntimeError" not in body
    assert json.loads(body)["error"].startswith("I couldn't process that request")


def test_a_failed_streamed_turn_says_something_general(server):
    base, runtime = server
    runtime.fail = True
    _, _, body = _post(base, "/ask/stream", {"question": "anything"})
    assert "event: error" in body
    assert "tms_secret_table" not in body and "RuntimeError" not in body


def test_no_web_page_may_read_the_answers(server):
    base, _ = server
    _, headers, _ = _post(base, "/ask", {"question": "anything"})
    assert not any(name.lower().startswith("access-control") for name in headers)


def test_this_machine_keeps_debug(server):
    base, runtime = server
    _, _, body = _post(base, "/ask", {"question": "anything", "debug": True})
    assert runtime.payloads[-1]["debug"] is True
    status, _, _ = _post(base, "/debug", {"session_id": "s"})
    assert status == 200


def test_another_machine_gets_neither_debug_nor_the_debug_log(server, monkeypatch):
    base, runtime = server
    monkeypatch.setattr(api, "_local_client", lambda address: False)

    status, _, _ = _post(base, "/debug", {"session_id": "s"})
    assert status == 403

    _post(base, "/ask", {"question": "anything", "debug": True})
    assert runtime.payloads[-1]["debug"] is False
    _post(base, "/ask/stream", {"question": "anything", "debug": True})
    assert runtime.payloads[-1]["debug"] is False


@pytest.mark.parametrize("address,local", [
    ("127.0.0.1", True), ("::1", True), ("::ffff:127.0.0.1", True),
    ("192.168.1.20", False), ("10.0.0.5", False),
])
def test_what_counts_as_this_machine(address, local):
    assert api._local_client(address) is local


# ------------------------------------------------------- the answer's shape --

from types import SimpleNamespace  # noqa: E402

from pipeline.context_pills import pill_ref  # noqa: E402
from pipeline.followup import FollowUp, Suggestion  # noqa: E402
from pipeline.lean_runner import TurnResult  # noqa: E402

NOTE = "This data is not updated in real time."
SETTINGS = SimpleNamespace(chatbot_user_id=0, freshness_tables=("vf_report_task_summary",),
                           freshness_message=NOTE, history_db_user="",
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
    api.SESSIONS.clear()
    rt = api.Runtime.__new__(api.Runtime)
    rt.settings, rt.gazetteer, rt.mcp_config_path = SETTINGS, [], None
    rt.privacy, rt.context_mode, rt.log_path = "strict", "state", None
    return rt, asked


def test_dropping_a_pill_asks_the_goal_again_without_it(runtime):
    rt, asked = runtime
    state = api.conversation_for("drop").state
    state.active_goal = "open tasks in Sales"
    state.active_filters = {"task_status": "task_status = 'open'"}

    rt.ask({"session_id": "drop", "drop_ref": pill_ref("task_status")})

    assert asked == ["open tasks in Sales"]
    assert "task_status" not in state.active_filters


def test_a_drop_with_nothing_to_ask_is_refused(runtime):
    rt, _ = runtime
    with pytest.raises(ValueError):
        rt.ask({"session_id": "nothing", "drop_ref": "0000000000"})


def test_a_chip_ref_asks_the_reading_it_was_offered_for(runtime):
    rt, asked = runtime
    state = api.conversation_for("chip").state
    state.pending_clarification = FollowUp(
        type="clarification", reason="ambiguous_interpretation", question="Which one?",
        suggestions=[Suggestion(id="a", label="Delayed open tasks", ref="n1:0")])

    rt.ask({"session_id": "chip", "question": "the first one", "option_ref": "n1:0"})
    rt.ask({"session_id": "chip", "question": "typed text", "option_ref": "stale:9"})

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
