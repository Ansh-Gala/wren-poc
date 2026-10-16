"""What each transport is allowed: the output cap, temperature, environment."""

from __future__ import annotations

from types import SimpleNamespace

from llm_api.cli_pool import MAX_OUTPUT_TOKENS, cli_environment
from llm_api.openai_provider import LEAN_MAX_TOKENS, _limits


def test_the_cap_is_the_one_drupal_gives_every_transport():
    assert LEAN_MAX_TOKENS == MAX_OUTPUT_TOKENS == 4000


def test_openai_gets_max_completion_tokens_and_no_temperature():
    """Its reasoning models reject both max_tokens and a set temperature."""
    assert _limits(SimpleNamespace(llm_provider="openai")) == {"max_completion_tokens": 4000}


def test_groq_and_gemini_keep_max_tokens_and_temperature_zero():
    for vendor in ("groq", "gemini"):
        assert _limits(SimpleNamespace(llm_provider=vendor)) == {
            "max_tokens": 4000, "temperature": 0}


def test_the_cli_runs_with_its_own_login_and_the_long_cache(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-not-for-the-cli")
    monkeypatch.setenv("DISABLE_PROMPT_CACHING_SONNET", "1")
    monkeypatch.setenv("FORCE_PROMPT_CACHING_5M", "1")
    env = cli_environment("C:/chatbot-claude")
    assert "ANTHROPIC_API_KEY" not in env
    assert "DISABLE_PROMPT_CACHING_SONNET" not in env
    assert "FORCE_PROMPT_CACHING_5M" not in env
    assert env["ENABLE_PROMPT_CACHING_1H"] == "1"
    assert env["CLAUDE_CODE_PROMPT_CACHE_TTL"] == "1h"
    assert env["CLAUDE_CODE_MAX_OUTPUT_TOKENS"] == "4000"
    assert env["CLAUDE_CONFIG_DIR"] == "C:/chatbot-claude"


def test_the_pool_gets_the_same_environment(monkeypatch):
    """It used to inherit ANTHROPIC_API_KEY when no config dir was set."""
    from llm_api.cli_pool import ClaudePool
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-not-for-the-cli")
    pool = ClaudePool.__new__(ClaudePool)
    pool._config_dir = ""
    assert "ANTHROPIC_API_KEY" not in pool._environment()
