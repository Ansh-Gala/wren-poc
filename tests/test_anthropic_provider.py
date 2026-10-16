"""The Anthropic API transport, with the SDK client stood in for: no API call."""

from __future__ import annotations

import dataclasses
import sys
from pathlib import Path
from types import SimpleNamespace

import anthropic
import httpx2
import pytest

from config.settings import Settings
from llm_api import anthropic_provider as ap
from llm_api.factory import get_provider, llm_identity
from pipeline.redact import safe_error

SETTINGS = Settings(pg_host="localhost", pg_port=5432, pg_database="d", pg_user="u",
                    llm_provider="anthropic", anthropic_api_key="sk-test",
                    anthropic_model="claude-opus-5-5", cli_lean=True)


class FakeClient:
    """Records the request and hands back a canned response or error."""

    def __init__(self, response=None, error=None):
        self.sent, self.response, self.error = None, response, error
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self._create))

    def close(self):
        pass

    def _create(self, **kwargs):
        self.sent = kwargs
        if self.error is not None:
            raise self.error
        return self.response


def _response(text='{"sql": "SELECT 1"}', stop="end_turn"):
    return SimpleNamespace(
        content=[SimpleNamespace(type="text", text=text)], stop_reason=stop,
        usage=SimpleNamespace(input_tokens=100, cache_creation_input_tokens=0,
                              cache_read_input_tokens=10000, output_tokens=50))


@pytest.fixture
def client(monkeypatch):
    fake = FakeClient(response=_response())
    monkeypatch.setattr(ap, "_client", lambda settings: fake)
    return fake


def test_the_factory_and_the_history_row_name_it():
    assert isinstance(get_provider(SETTINGS), ap.AnthropicProvider)
    assert llm_identity(SETTINGS) == ("api", "anthropic", "claude-opus-5-5")


def test_the_schema_is_cached_for_an_hour_and_the_question_comes_after(client):
    ap.AnthropicProvider().ask("how many tasks?", None, "strict", SETTINGS)
    system = client.sent["system"]
    assert system[0]["cache_control"] == {"type": "ephemeral", "ttl": "1h"}
    assert "how many tasks?" not in system[0]["text"]
    assert "how many tasks?" in client.sent["messages"][0]["content"]
    assert client.sent["max_tokens"] == 4000
    assert client.sent["model"] == "claude-opus-5-5"


def test_refusals_fall_back_server_side(client):
    ap.AnthropicProvider().ask("q", None, "strict", SETTINGS)
    assert client.sent["fallbacks"] == "default"
    assert client.sent["betas"] == [ap.FALLBACK_BETA]


def test_tokens_are_counted_as_the_cli_counts_them(client):
    run = ap.AnthropicProvider().ask("q", None, "strict", SETTINGS)
    assert run.ok and run.result_text == '{"sql": "SELECT 1"}'
    assert (run.prompt_tokens, run.cache_read_tokens, run.completion_tokens) == (10100, 10000, 50)


def test_the_whole_reply_is_handed_over_once(client):
    seen = []
    ap.AnthropicProvider().ask("q", None, "strict", SETTINGS, on_delta=seen.append)
    assert seen == ['{"sql": "SELECT 1"}']


def test_a_refusal_is_a_failure_not_an_empty_answer(monkeypatch):
    monkeypatch.setattr(ap, "_client", lambda s: FakeClient(response=_response("", "refusal")))
    run = ap.AnthropicProvider().ask("q", None, "strict", SETTINGS)
    assert not run.ok and "declined" in run.error


@pytest.mark.parametrize("status,starts", [
    (401, "Authentication failed"), (429, "Too many requests"),
    (503, "The AI service is temporarily unavailable"),
])
def test_an_http_failure_says_what_kind_it_was(monkeypatch, status, starts):
    response = httpx2.Response(status, request=httpx2.Request("POST", "https://api.anthropic.com"))
    error = anthropic.APIStatusError("upstream said no", response=response, body=None)
    monkeypatch.setattr(ap, "_client", lambda s: FakeClient(error=error))
    run = ap.AnthropicProvider().ask("q", None, "strict", SETTINGS)
    assert not run.ok and run.error.startswith(f"anthropic returned HTTP {status}")
    assert safe_error(run.error).startswith(starts)


def test_no_key_is_said_before_anything_is_sent(monkeypatch):
    called = []
    monkeypatch.setattr(ap, "_client", lambda s: called.append(1))
    run = ap.AnthropicProvider().ask("q", None, "strict",
                                     dataclasses.replace(SETTINGS, anthropic_api_key=""))
    assert not run.ok and called == []
    assert safe_error(run.error).startswith("Authentication failed")


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))


def test_the_server_starts_on_an_api_with_its_key_and_not_without():
    import scripts.serve_api as api
    api.preflight(SETTINGS)
    with pytest.raises(SystemExit, match="ANTHROPIC_API_KEY"):
        api.preflight(dataclasses.replace(SETTINGS, anthropic_api_key=""))
    with pytest.raises(SystemExit, match="Use cli, anthropic"):
        api.preflight(dataclasses.replace(SETTINGS, llm_provider="mystery"))
