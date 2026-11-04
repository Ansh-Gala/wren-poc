"""The lean branch must send what the Drupal port sends, and nothing else.

src/Llm/OpenAiCompatibleProvider.php is one POST: the lean system prompt, the
lean user prompt, no tools, one round trip. Until this branch existed,
LLM_PROVIDER=groq with CLI_LEAN=1 quietly ran the MCP agent loop instead --
a different prompt, a different number of calls, and a measurement of a
transport that does not ship.

The failure these tests exist to catch is silent: an MCP-shaped call still
returns an answer, so a suite run would score fine while measuring the wrong
thing.
"""

import types

import pytest

from claude.prompts import build_lean_system_prompt, build_user_prompt
from config.settings import Settings
from llm_api import mcp_bridge, openai_provider
from llm_api.openai_provider import LEAN_MAX_TOKENS, OpenAIProvider


def _settings(**over):
    fields = {
        "pg_host": "localhost", "pg_port": 5432, "pg_database": "wren_demo",
        "pg_user": "postgres",
        "cli_lean": True,
        "openai_api_key": "k",
        "openai_model": "llama-3.3-70b-versatile",
        "openai_base_url": "https://api.groq.com/openai/v1",
    }
    fields.update(over)
    return Settings(**fields)


@pytest.fixture
def calls(monkeypatch):
    """Capture every request the provider makes, and answer them."""
    seen = []

    class FakeCompletions:
        async def create(self, **kwargs):
            seen.append(kwargs)
            return types.SimpleNamespace(
                choices=[types.SimpleNamespace(
                    message=types.SimpleNamespace(
                        content='{"sql": "SELECT 1"}', tool_calls=None))],
                usage=types.SimpleNamespace(
                    prompt_tokens=10929, completion_tokens=80,
                    prompt_tokens_details=types.SimpleNamespace(cached_tokens=10636)),
            )

    class FakeClient:
        def __init__(self, **kwargs):
            self.chat = types.SimpleNamespace(completions=FakeCompletions())

        async def close(self):
            pass

        # The MCP path opens the client with `async with`.
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            pass

    monkeypatch.setattr(openai_provider, "AsyncOpenAI", FakeClient)

    # Constructing the bridge spawns the Wren MCP server. In lean mode nothing
    # may reach it, so reaching it is the failure, not a slow test.
    def no_bridge(*a, **k):
        raise AssertionError("lean mode opened the MCP bridge")

    monkeypatch.setattr(mcp_bridge, "WrenMCPBridge", no_bridge)
    return seen


def test_openai_sends_one_stable_cache_key_and_no_lifetime_fields(calls):
    settings = _settings(llm_provider="openai", openai_base_url=None)
    OpenAIProvider().ask("Show the open tasks", None, "strict", settings)
    OpenAIProvider().ask("And the closed ones", None, "strict", settings)
    assert calls[0]["prompt_cache_key"].startswith("wren-")
    assert calls[0]["prompt_cache_key"] == calls[1]["prompt_cache_key"]
    # Deprecated, and not accepted by every model; the gpt-5.6 replacement
    # only exists from gpt-5.6, and its sole ttl is the default anyway.
    assert "prompt_cache_retention" not in calls[0]
    assert "prompt_cache_options" not in calls[0]


LUNA = {"llm_provider": "openai", "openai_base_url": None, "openai_model": "gpt-5.6-luna"}
BREAKPOINT_12H = {"mode": "explicit", "ttl": "12h"}


def test_the_default_openai_model_is_gpt_5_6_luna():
    assert Settings(pg_host="h", pg_port=1, pg_database="d", pg_user="u").openai_model \
        == "gpt-5.6-luna"


def test_gpt_5_6_caches_only_the_static_prompt_for_12_hours(calls):
    OpenAIProvider().ask("Show the open tasks", None, "strict", _settings(**LUNA))
    system, user = calls[0]["messages"]
    assert system["content"] == [{"type": "text", "text": build_lean_system_prompt(),
                                  "prompt_cache_breakpoint": BREAKPOINT_12H}]
    assert isinstance(user["content"], str)            # the question: after, never written
    assert calls[0]["prompt_cache_options"] == {"mode": "explicit"}
    # The key still comes from the prompt's text, not from the list around it.
    OpenAIProvider().ask("Show the open tasks", None, "strict",
                         _settings(llm_provider="openai", openai_base_url=None))
    assert calls[0]["prompt_cache_key"] == calls[1]["prompt_cache_key"]


def test_a_streamed_gpt_5_6_question_sends_the_same_cache_fields(calls):
    OpenAIProvider().ask("Show the open tasks", None, "strict", _settings(**LUNA),
                         on_delta=lambda piece: None)
    assert calls[0]["stream"] is True
    assert calls[0]["prompt_cache_options"] == {"mode": "explicit"}
    assert calls[0]["messages"][0]["content"][0]["prompt_cache_breakpoint"] == BREAKPOINT_12H


@pytest.mark.parametrize("model", ["gpt-5.5", "gpt-4o", "o3"])
def test_older_models_get_the_key_and_a_plain_system_prompt(calls, model):
    OpenAIProvider().ask("Show the open tasks", None, "strict",
                         _settings(llm_provider="openai", openai_base_url=None,
                                   openai_model=model))
    assert calls[0]["prompt_cache_key"].startswith("wren-")
    assert "prompt_cache_options" not in calls[0]
    assert calls[0]["messages"][0]["content"] == build_lean_system_prompt()


def test_mcp_turns_send_the_cache_key_and_count_cached_tokens(calls, monkeypatch):
    from contextlib import asynccontextmanager

    from wren_setup.mcp_config import allowed_tools, to_mcp_name

    class Session:
        async def list_tools(self):
            name = to_mcp_name(allowed_tools("strict")[0])
            return types.SimpleNamespace(tools=[types.SimpleNamespace(name=name)])

    class Bridge:
        def __init__(self, *args):
            pass

        @asynccontextmanager
        async def get_session(self):
            yield Session()

        def to_openai_tool(self, tool):
            return {"type": "function", "function": {"name": tool.name, "parameters": {}}}

    monkeypatch.setattr(mcp_bridge, "WrenMCPBridge", Bridge)
    run = OpenAIProvider().ask("Show the open tasks", None, "strict",
                               _settings(**LUNA, cli_lean=False))
    assert calls[0]["prompt_cache_key"].startswith("wren-")
    # Implicit: OpenAI also caches the turns so far, for the next turn.
    assert calls[0]["prompt_cache_options"] == {"mode": "implicit"}
    assert calls[0]["messages"][0]["content"][0]["prompt_cache_breakpoint"] == BREAKPOINT_12H
    assert run.cache_read_tokens == 10636


def test_compatible_endpoints_get_no_openai_cache_fields(calls):
    OpenAIProvider().ask("Show the open tasks", None, "strict", _settings(llm_provider="groq"))
    assert "prompt_cache_key" not in calls[0] and "prompt_cache_retention" not in calls[0]


def test_lean_sends_exactly_one_request(calls):
    OpenAIProvider().ask("Show the open tasks", None, "strict", _settings())
    assert len(calls) == 1


def test_lean_sends_the_lean_prompts(calls):
    OpenAIProvider().ask("Show the open tasks", None, "strict", _settings())
    messages = calls[0]["messages"]
    assert [m["role"] for m in messages] == ["system", "user"]
    assert messages[0]["content"] == build_lean_system_prompt()
    assert messages[1]["content"] == build_user_prompt("Show the open tasks", None, lean=True)


def test_lean_offers_no_tools(calls):
    OpenAIProvider().ask("Show the open tasks", None, "strict", _settings())
    assert "tools" not in calls[0]


def test_lean_pins_the_model_and_the_ceiling(calls):
    OpenAIProvider().ask("Show the open tasks", None, "strict", _settings())
    assert calls[0]["model"] == "llama-3.3-70b-versatile"
    assert calls[0]["max_tokens"] == LEAN_MAX_TOKENS
    # The same question twice must not produce two different queries; the
    # suite's accuracy figure leans on it.
    assert calls[0]["temperature"] == 0


def test_the_system_prompt_comes_first_or_the_cache_is_wasted(calls):
    # ~10.7k tokens of schema, identical on every question. All three
    # providers cache on a prefix match, so anything question-specific placed
    # ahead of it throws the whole cache away on every request.
    OpenAIProvider().ask("Show the open tasks", None, "strict", _settings())
    assert calls[0]["messages"][0]["role"] == "system"


def test_lean_reports_the_tokens_the_suite_averages(calls):
    run = OpenAIProvider().ask("Show the open tasks", None, "strict", _settings())
    assert run.ok
    assert run.result_text == '{"sql": "SELECT 1"}'
    assert (run.prompt_tokens, run.completion_tokens) == (10929, 80)
    assert run.cache_read_tokens == 10636


def test_a_missing_key_is_reported_rather_than_thrown(calls):
    run = OpenAIProvider().ask("q", None, "strict", _settings(openai_api_key=""))
    assert not run.ok and "OPENAI_API_KEY" in run.error
    assert calls == []


async def _closed():
    pass


def test_an_empty_reply_is_not_ok(monkeypatch, calls):
    class Empty:
        async def create(self, **kwargs):
            calls.append(kwargs)
            return types.SimpleNamespace(
                choices=[types.SimpleNamespace(
                    message=types.SimpleNamespace(content="", tool_calls=None))],
                usage=None)

    monkeypatch.setattr(openai_provider, "AsyncOpenAI",
                        lambda **k: types.SimpleNamespace(
                            chat=types.SimpleNamespace(completions=Empty()),
                            close=_closed))
    run = OpenAIProvider().ask("q", None, "strict", _settings())
    assert not run.ok and run.error
