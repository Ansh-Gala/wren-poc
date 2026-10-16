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
