from __future__ import annotations

import abc
from collections.abc import Callable
from pathlib import Path

from pipeline.models import ClaudeRun, Session
from config.settings import Settings

class LLMProvider(abc.ABC):
    """Abstract base class for LLM text-to-SQL providers."""

    @abc.abstractmethod
    def ask(
        self,
        question: str,
        mcp_config_path: Path,
        privacy_mode: str,
        settings: Settings,
        session: Session | None = None,
        on_delta: Callable[[str], None] | None = None,
    ) -> ClaudeRun:
        """Query the LLM to generate SQL.

        Args:
            question: The natural language question to answer.
            mcp_config_path: Path to the MCP config (for CLI) or ignored if direct.
            privacy_mode: Strict or validated.
            settings: Benchmark settings.
            session: Optional conversation history.
            on_delta: Called with each fragment of the reply as it arrives.
                The returned ClaudeRun is unchanged either way -- this only
                offers the caller the text sooner. The contract puts `sql`
                first in the object, and it is complete a mean of 2.02s before
                the last token, so a caller that watches for it can run the
                query in that gap rather than after it. A provider that cannot
                stream may ignore this and still be correct, only slower.

        Returns:
            ClaudeRun containing the generated text, timing, and tool usage.
        """
        pass
