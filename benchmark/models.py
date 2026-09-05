"""Data carriers shared across the benchmark. No behaviour lives here."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class Question:
    id: str
    category: str
    question: str
    expected_sql: str
    ordered: bool = False
    tags: list[str] = field(default_factory=list)
    interpretation: str | None = None


@dataclass(frozen=True)
class ParsedSQL:
    """Result of extracting SQL from Claude's free-form reply.

    ``strategy`` records which extraction path matched, so parser fragility is
    itself a measurable outcome rather than an invisible failure mode.
    """

    sql: str | None
    strategy: str
    raw: str


@dataclass
class QueryResult:
    columns: list[str]
    rows: list[tuple]
    duration_ms: float
    error: str | None = None
    sqlstate: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None


@dataclass
class ClaudeRun:
    """Outcome of one `claude -p` subprocess."""

    ok: bool
    exit_code: int | None = None
    timed_out: bool = False
    duration_ms: float = 0.0
    result_text: str = ""
    tools_used: list[str] = field(default_factory=list)
    mcp_errors: list[str] = field(default_factory=list)
    cost_usd: float | None = None
    session_id: str | None = None
    num_turns: int | None = None
    stderr: str = ""
    error: str | None = None
    prompt_tokens: int = 0
    completion_tokens: int = 0
    # Anthropic bills cache writes and reads separately from fresh input.
    # Recorded so the effect of prompt caching is visible rather than assumed.
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0


@dataclass
class QuestionResult:
    """One benchmark record. Field set follows section 19 of the brief."""

    question_id: str = ""
    category: str = ""
    question: str = ""
    expected_sql: str = ""
    generated_sql: str | None = None

    sql_valid: bool = False
    execution_success: bool = False
    result_match: bool = False

    expected_result: dict[str, Any] | None = None
    actual_result: dict[str, Any] | None = None

    claude_time_ms: float = 0.0
    sql_execution_time_ms: float = 0.0
    total_time_ms: float = 0.0

    error: str | None = None
    failure_category: str | None = None

    prompt_tokens: int = 0
    completion_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0

    # Signals the classifier depends on.
    parse_strategy: str = "none"
    tools_used: list[str] = field(default_factory=list)
    # How many of tools_used were Wren MCP tools. Zero means the semantic
    # layer contributed nothing and the record measures Claude alone.
    wren_tool_calls: int = 0
    mcp_errors: list[str] = field(default_factory=list)
    sqlstate: str | None = None
    timed_out: bool = False
    cli_ok: bool = True
    tags: list[str] = field(default_factory=list)

    # Run provenance.
    config_name: str = ""
    privacy_mode: str = ""
    raw_output: str = ""

@dataclass
class Turn:
    index: int
    question: str
    generated_sql: str | None

@dataclass
class Session:
    session_id: str
    turns: list[Turn] = field(default_factory=list)
    # Rendered by benchmark.context. When set, providers send this instead of
    # replaying `turns`, which keeps prompt size flat across a long thread.
    context_block: str | None = None
    lean: bool = False
