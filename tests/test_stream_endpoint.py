"""POST /ask/stream, against a real socket.

The point of the endpoint is ordering -- `rows` has to reach the browser
before `answer`, or the two seconds it exists to save are not saved. That is
not something a unit test on the Runtime can show, so these go through the
actual server.

The model is scripted; the database is real, because the rows are the thing
being delivered early.
"""

from __future__ import annotations

import json
import sys
import threading
import urllib.request
from pathlib import Path

import pytest

from pipeline.models import ClaudeRun

# serve_api imports _bootstrap, which sits beside it. Running the script
# directly puts that directory on the path; importing it as a module does not.
SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

pytestmark = pytest.mark.integration


COUNT_SQL = ('{"sql": "SELECT COUNT(*) FROM tms_initiative_flat", '
             '"explanation": "how many initiatives there are", '
             '"next": ["break it down by status"]}')


class ScriptedProvider:
    def __init__(self, text):
        self.text = text

    def ask(self, question, mcp_config_path, privacy_mode, settings,
            session=None, on_delta=None):
        if on_delta is not None:
            for i in range(0, len(self.text), 10):
                on_delta(self.text[i:i + 10])
        return ClaudeRun(ok=True, result_text=self.text, duration_ms=1.0)


@pytest.fixture
def server(monkeypatch, settings):
    """A live server on a free port, with the model scripted."""
    import scripts.serve_api as api

    monkeypatch.setattr("pipeline.lean_runner.get_provider",
                        lambda s: ScriptedProvider(COUNT_SQL))
    api.SESSIONS.clear()

    runtime = api.Runtime.__new__(api.Runtime)
    runtime.settings = settings
    runtime.gazetteer = []
    runtime.mcp_config_path = None
    runtime.privacy = "strict"
    runtime.context_mode = "state"
    runtime.log_path = None
    runtime.record = lambda *a, **k: None
    api.Handler.runtime = runtime

    httpd = api.ThreadingHTTPServer(("127.0.0.1", 0), api.Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()
    httpd.server_close()


def _events(base, body):
    """Every SSE event the endpoint sent, in the order it sent them."""
    request = urllib.request.Request(
        base + "/ask/stream", data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"})
    raw = urllib.request.urlopen(request, timeout=60).read().decode()

    out = []
    for block in raw.split("\n\n"):
        name = data = None
        for line in block.splitlines():
            if line.startswith("event: "):
                name = line[7:]
            elif line.startswith("data: "):
                data = json.loads(line[6:])
        if name:
            out.append((name, data))
    return out


def test_the_rows_are_sent_before_the_answer(server):
    events = _events(server, {"question": "how many?", "session_id": "s1",
                              "debug": True})
    assert [name for name, _ in events] == ["rows", "answer"]

    rows = dict(events)["rows"]
    assert rows["generated_sql"] == "SELECT COUNT(*) FROM tms_initiative_flat"
    assert rows["result"]["rows"], "the rows event carried no rows"


def test_the_answer_is_the_whole_response(server):
    events = _events(server, {"question": "how many?", "session_id": "s2",
                              "debug": True})
    answer = dict(events)["answer"]
    # A client may ignore `rows` entirely and still have everything, which is
    # what keeps this additive rather than a second contract.
    assert answer["explanation" if "explanation" in answer else "generated_sql"]
    assert answer["result"]["rows"]
    assert answer["followup"] is not None
    assert answer["state"]["previous_sql"]


def test_debug_off_keeps_the_sql_out_of_the_rows_event(server):
    """A field the browser receives has already left the server."""
    events = _events(server, {"question": "how many?", "session_id": "s3"})
    rows = dict(events)["rows"]
    assert "generated_sql" not in rows
    assert "raw_error" not in rows
    # The table still arrives -- redaction removes the schema, not the answer.
    assert rows["result"]["rows"]
    assert "columns" not in rows["result"]


def test_a_clarification_sends_only_the_answer(monkeypatch, server):
    monkeypatch.setattr(
        "pipeline.lean_runner.get_provider",
        lambda s: ScriptedProvider('{"clarify": "which department did you mean?"}'))
    events = _events(server, {"question": "how many?", "session_id": "s4",
                              "debug": True})
    assert [name for name, _ in events] == ["answer"]
    assert dict(events)["answer"]["clarification"]


def test_plain_ask_is_unchanged(server):
    """The existing endpoint must answer exactly as it did before."""
    request = urllib.request.Request(
        server + "/ask",
        data=json.dumps({"question": "how many?", "session_id": "s5",
                         "debug": True}).encode(),
        headers={"Content-Type": "application/json"})
    body = json.loads(urllib.request.urlopen(request, timeout=60).read())
    assert body["generated_sql"] == "SELECT COUNT(*) FROM tms_initiative_flat"
    assert body["result"]["rows"]
