"""Ask the Anthropic Messages API, through the official SDK.

Ported from the Drupal port's AnthropicApiProvider: one request per question,
the lean system prompt marked cacheable for an hour -- it inlines the whole
schema, identical on every question, and about one question in six arrives
5-60 minutes after the last, where only the longer cache entry is still alive
-- and the same 4000-token output cap every transport gets.

One addition Drupal does not make: refusal fallbacks. On a policy decline the
API re-runs the request on a fallback model inside the same call, so a refused
question can still be answered.

No retries, as in Drupal: a turn has a time budget, and a second attempt on a
rate limit would spend it twice.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from pathlib import Path

import anthropic

from claude.prompts import build_lean_system_prompt, build_user_prompt
from config.settings import Settings
from llm_api.cli_pool import MAX_OUTPUT_TOKENS
from llm_api.provider import LLMProvider
from pipeline.models import ClaudeRun, Session

# Server-side refusal fallbacks, routed by refusal category.
FALLBACK_BETA = "server-side-fallback-2026-07-01"


def _client(settings: Settings) -> anthropic.Anthropic:
    """The SDK client. A function of its own so a test can stand in for it."""
    return anthropic.Anthropic(api_key=settings.anthropic_api_key,
                               timeout=float(settings.claude_timeout_seconds),
                               max_retries=0)


class AnthropicProvider(LLMProvider):
    def ask(
        self,
        question: str,
        mcp_config_path: Path,
        privacy_mode: str,
        settings: Settings,
        session: Session | None = None,
        on_delta: Callable[[str], None] | None = None,
    ) -> ClaudeRun:
        if not settings.anthropic_api_key:
            return ClaudeRun(ok=False, error="ANTHROPIC_API_KEY is not set.")
        if not settings.anthropic_model:
            return ClaudeRun(ok=False, error="No Anthropic model chosen. Set ANTHROPIC_MODEL.")

        started = time.perf_counter()
        client = _client(settings)
        try:
            response = client.beta.messages.create(
                model=settings.anthropic_model,
                max_tokens=MAX_OUTPUT_TOKENS,
                # The schema is identical on every question, so mark it
                # cacheable; nothing question-specific may come before it.
                system=[{"type": "text", "text": build_lean_system_prompt(),
                         "cache_control": {"type": "ephemeral", "ttl": "1h"}}],
                messages=[{"role": "user", "content": build_user_prompt(
                    question, session,
                    context=session.context_block if session else None, lean=True)}],
                betas=[FALLBACK_BETA],
                fallbacks="default",
            )
        except anthropic.APIStatusError as exc:
            # The status leads, so a failure can be told apart: 401, 429,
            # 5xx. The message never quotes the key, which is a header.
            return ClaudeRun(ok=False, duration_ms=_ms(started),
                             error=f"anthropic returned HTTP {exc.status_code}: {exc.message}")
        except (anthropic.APIConnectionError, anthropic.APITimeoutError) as exc:
            return ClaudeRun(ok=False, duration_ms=_ms(started), timed_out=isinstance(
                exc, anthropic.APITimeoutError), error=f"anthropic request failed: {exc}")
        finally:
            client.close()          # its connection pool, made for this one call

        elapsed = _ms(started)
        usage = response.usage
        tokens = {
            # As in the CLI: fresh input plus both cache counters.
            "prompt_tokens": (usage.input_tokens or 0) + (usage.cache_creation_input_tokens or 0)
            + (usage.cache_read_input_tokens or 0),
            "completion_tokens": usage.output_tokens or 0,
            "cache_read_tokens": usage.cache_read_input_tokens or 0,
            "cache_write_tokens": usage.cache_creation_input_tokens or 0,
        }
        if response.stop_reason == "refusal":
            # The whole chain declined, fallback included.
            return ClaudeRun(ok=False, duration_ms=elapsed,
                             error="anthropic declined the request", **tokens)

        # A lean turn calls no tools, so the text blocks are the whole reply.
        text = "".join(block.text for block in response.content if block.type == "text")
        # No streaming here: the whole reply, once, as the caller's contract allows.
        if on_delta is not None and text:
            on_delta(text)
        return ClaudeRun(ok=bool(text), duration_ms=elapsed, result_text=text,
                         error=None if text else "anthropic returned no text block", **tokens)


def _ms(started: float) -> float:
    return (time.perf_counter() - started) * 1000
