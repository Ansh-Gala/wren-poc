from __future__ import annotations

import abc
from pathlib import Path

from benchmark.models import ClaudeRun, Session
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
    ) -> ClaudeRun:
        """Query the LLM to generate SQL.

        Args:
            question: The natural language question to answer.
            mcp_config_path: Path to the MCP config (for CLI) or ignored if direct.
            privacy_mode: Strict or validated.
            settings: Benchmark settings.
            session: Optional conversation history.

        Returns:
            ClaudeRun containing the generated text, timing, and tool usage.
        """
        pass
