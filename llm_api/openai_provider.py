import asyncio
import json
import time
from pathlib import Path

import nest_asyncio
from openai import AsyncOpenAI
from openai.types.chat import ChatCompletionMessageParam, ChatCompletionToolMessageParam

from benchmark.models import ClaudeRun, Session
from config.settings import Settings
from wren_setup.mcp_config import allowed_tools, to_claude_name, to_mcp_name
from llm_api.provider import LLMProvider
from llm_api.mcp_bridge import WrenMCPBridge
from claude.prompts import build_system_prompt, build_user_prompt

nest_asyncio.apply()

# An agent loop with no ceiling is both a hang risk and an unbounded bill: every
# turn resends the whole conversation. Real runs settle in 2-3 tool calls, so
# this only ever fires on a model that has got stuck.
MAX_TURNS = 8

# A single tool result must not be allowed to dominate the context. The cap is
# generous next to what the allowed tools actually return (the largest,
# describe_model, is ~880 tokens) and only bites on a pathological payload.
MAX_TOOL_RESULT_CHARS = 8000


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
    ) -> ClaudeRun:
        return asyncio.run(self._ask_async(question, privacy_mode, settings, session))

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
        
        async with bridge.get_session() as mcp_session:
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
            
            return ClaudeRun(
                ok=True,
                duration_ms=elapsed_ms,
                result_text=result_text,
                tools_used=tools_used,
                mcp_errors=mcp_errors,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens
            )
