import asyncio
import json
import time
from collections.abc import Callable
from pathlib import Path

from openai import AsyncOpenAI
from openai.types.chat import ChatCompletionMessageParam

from pipeline.models import ClaudeRun, Session
from config.settings import Settings
from wren_setup.mcp_config import allowed_tools, to_claude_name, to_mcp_name
from llm_api.cli_pool import MAX_OUTPUT_TOKENS
from llm_api.provider import LLMProvider
from llm_api.mcp_bridge import WrenMCPBridge
from claude.prompts import build_lean_system_prompt, build_system_prompt, build_user_prompt

# An agent loop with no ceiling is both a hang risk and an unbounded bill: every
# turn resends the whole conversation. Real runs settle in 2-3 tool calls, so
# this only ever fires on a model that has got stuck.
MAX_TURNS = 8

# A single tool result must not be allowed to dominate the context. The cap is
# generous next to what the allowed tools actually return (the largest,
# describe_model, is ~880 tokens) and only bites on a pathological payload.
MAX_TOOL_RESULT_CHARS = 8000

# A ceiling on the lean reply, which is a SELECT and a few sentences. The same
# figure the Drupal port uses for every transport (LlmProviderInterface::
# MAX_TOKENS), so a model is not given more room here than it gets there.
LEAN_MAX_TOKENS = MAX_OUTPUT_TOKENS


def _limits(settings: Settings) -> dict:
    """The output cap and temperature, in the form each vendor accepts.

    OpenAI's reasoning models reject max_tokens and any non-default
    temperature; Groq and Gemini still expect both. As the Drupal port sends.
    """
    if settings.llm_provider == "openai":
        return {"max_completion_tokens": LEAN_MAX_TOKENS}
    return {"max_tokens": LEAN_MAX_TOKENS, "temperature": 0}


def _cap(text: str) -> str:
    if len(text) <= MAX_TOOL_RESULT_CHARS:
        return text
    dropped = len(text) - MAX_TOOL_RESULT_CHARS
    return text[:MAX_TOOL_RESULT_CHARS] + f"\n... [truncated {dropped} chars]"


class OpenAIProvider(LLMProvider):
    def ask(
        self,
        question: str,
        mcp_config_path: Path,
        privacy_mode: str,
        settings: Settings,
        session: Session | None = None,
        on_delta: Callable[[str], None] | None = None,
    ) -> ClaudeRun:
        if settings.cli_lean:
            return asyncio.run(self._ask_lean(question, settings, session, on_delta))
        return asyncio.run(self._ask_async(question, privacy_mode, settings, session))

    async def _ask_lean(
        self,
        question: str,
        settings: Settings,
        session: Session | None = None,
        on_delta: Callable[[str], None] | None = None,
    ) -> ClaudeRun:
        """One call, the whole semantic layer in the system prompt, no tools.

        The shape the Drupal port has always used -- src/Llm/
        OpenAiCompatibleProvider.php sends exactly this -- and the shape
        CLILocalProvider switches to under the same flag. Only this class was
        left behind, so asking Groq or Gemini a question in lean mode ran the
        MCP agent loop instead: up to eight round trips to measure a transport
        that ships as one.

        Nothing question-specific may precede the system prompt. All three
        providers cache on a prefix match, and the prompt is ~10.7k tokens of
        schema identical on every question, so a byte moved in front of it
        throws the whole cache away.
        """
        started = time.perf_counter()

        if not settings.openai_api_key:
            return ClaudeRun(ok=False, error="OPENAI_API_KEY is not set.")

        client = AsyncOpenAI(
            api_key=settings.openai_api_key,
            base_url=settings.openai_base_url,
        )

        messages: list[ChatCompletionMessageParam] = [
            {"role": "system", "content": build_lean_system_prompt()},
            {"role": "user", "content": build_user_prompt(
                question, session,
                context=session.context_block if session else None,
                lean=True)},
        ]

        try:
            if on_delta is None:
                response = await client.chat.completions.create(
                    model=settings.openai_model,
                    messages=messages,
                    **_limits(settings),
                )
                text = response.choices[0].message.content or ""
                usage = response.usage
            else:
                text, usage = await self._stream_lean(
                    client, settings, messages, on_delta)
        except Exception as e:
            return ClaudeRun(
                ok=False,
                error=str(e),
                duration_ms=(time.perf_counter() - started) * 1000,
            )
        finally:
            await client.close()     # its connection pool, made for this one call

        elapsed_ms = (time.perf_counter() - started) * 1000

        return ClaudeRun(
            ok=text != "",
            duration_ms=elapsed_ms,
            result_text=text,
            error=None if text else "the model returned no message content",
            prompt_tokens=(usage.prompt_tokens or 0) if usage else 0,
            completion_tokens=(usage.completion_tokens or 0) if usage else 0,
            # What the provider served from its own cache. OpenAI reports it
            # here; Groq and Gemini omit it, which reads as zero.
            cache_read_tokens=(
                (getattr(usage, "prompt_tokens_details", None)
                 and getattr(usage.prompt_tokens_details, "cached_tokens", 0)) or 0
            ) if usage else 0,
        )

    async def _stream_lean(self, client, settings, messages, on_delta):
        """The same call, delivered as it is produced.

        `stream_options.include_usage` is sent because a streamed response
        carries no usage block unless it is asked for, and the suite averages
        those figures -- a streamed turn reporting zero tokens would quietly
        pull every average down.
        """
        text = ""
        usage = None
        stream = await client.chat.completions.create(
            model=settings.openai_model,
            messages=messages,
            **_limits(settings),
            stream=True,
            stream_options={"include_usage": True},
        )
        async for chunk in stream:
            if chunk.usage:
                usage = chunk.usage
            if not chunk.choices:
                # The usage block arrives in a final chunk of its own, with
                # no choices to index.
                continue
            piece = chunk.choices[0].delta.content or ""
            if piece:
                text += piece
                on_delta(piece)
        return text, usage

    async def _ask_async(
        self,
        question: str,
        privacy_mode: str,
        settings: Settings,
        session: Session | None = None,
    ) -> ClaudeRun:
        started = time.perf_counter()
        
        if not settings.openai_api_key:
            return ClaudeRun(ok=False, error="OPENAI_API_KEY is not set.")
            
        client = AsyncOpenAI(
            api_key=settings.openai_api_key,
            base_url=settings.openai_base_url
        )
        
        bridge = WrenMCPBridge(settings.benchmark_config, privacy_mode, settings)
        
        # The client too: its connection pool is made for this one question.
        async with client, bridge.get_session() as mcp_session:
            tools_response = await mcp_session.list_tools()
            
            allowed = set(allowed_tools(privacy_mode))
            # The MCP server answers to bare names ("dry_plan"); allowed_tools
            # returns Claude Code's addressing form ("mcp__wren__dry_plan").
            # Comparing the two directly matched nothing, so tools=None was
            # sent and the model never learned Wren existed.
            mcp_tools = [t for t in tools_response.tools if to_claude_name(t.name) in allowed]
            if not mcp_tools:
                return ClaudeRun(
                    ok=False,
                    error=(
                        "no allowed Wren tools matched the MCP server's tool list "
                        f"(server offers {sorted(t.name for t in tools_response.tools)}). "
                        "Answering without the semantic layer would measure the model alone."
                    ),
                )
            openai_tools = [bridge.to_openai_tool(t) for t in mcp_tools]
            
            messages: list[ChatCompletionMessageParam] = [
                {"role": "system", "content": build_system_prompt()},
                {"role": "user", "content": build_user_prompt(
                    question, session,
                    context=session.context_block if session else None)}
            ]
            
            tools_used = []
            mcp_errors = []
            result_text = ""
            prompt_tokens = 0
            completion_tokens = 0
            
            try:
                for _turn in range(MAX_TURNS):
                    response = await client.chat.completions.create(
                        model=settings.openai_model,
                        messages=messages,
                        tools=openai_tools if openai_tools else None,
                        temperature=0,
                    )
                    
                    if response.usage:
                        prompt_tokens += response.usage.prompt_tokens or 0
                        completion_tokens += response.usage.completion_tokens or 0
                        
                    msg = response.choices[0].message
                    messages.append(msg)
                    
                    if not msg.tool_calls:
                        # Model is done
                        result_text = msg.content or ""
                        break
                        
                    for tool_call in msg.tool_calls:
                        # Recorded in Claude Code's spelling so wren_tool_calls()
                        # counts the same way for both providers.
                        tools_used.append(to_claude_name(tool_call.function.name))
                        try:
                            args = json.loads(tool_call.function.arguments)
                        except json.JSONDecodeError:
                            args = {}

                        # Call MCP
                        try:
                            result = await mcp_session.call_tool(
                                to_mcp_name(tool_call.function.name), args
                            )
                            content_str = "\n".join([c.text for c in result.content if c.type == "text"])
                            if result.isError:
                                mcp_errors.append(content_str)
                        except Exception as e:
                            content_str = f"Error calling tool: {e}"
                            mcp_errors.append(content_str)

                        content_str = _cap(content_str)

                        messages.append({
                            "role": "tool",
                            "tool_call_id": tool_call.id,
                            "content": content_str,
                        })
            except Exception as e:
                return ClaudeRun(
                    ok=False,
                    error=str(e),
                    duration_ms=(time.perf_counter() - started) * 1000,
                    tools_used=tools_used,
                    mcp_errors=mcp_errors,
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens
                )
                
            elapsed_ms = (time.perf_counter() - started) * 1000
            
            # Every turn asked for a tool: there is no answer to report.
            return ClaudeRun(
                ok=bool(result_text),
                error=None if result_text else f"no final answer after {MAX_TURNS} turns",
                duration_ms=elapsed_ms,
                result_text=result_text,
                tools_used=tools_used,
                mcp_errors=mcp_errors,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens
            )
