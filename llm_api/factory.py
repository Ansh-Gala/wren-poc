from config.settings import Settings
from llm_api.provider import LLMProvider

def get_provider(settings: Settings) -> LLMProvider:
    provider = settings.llm_provider
    if provider == "cli":
        from llm_api.cli_provider import CLILocalProvider
        return CLILocalProvider()
    elif provider in ("openai", "groq", "gemini"):
        from llm_api.openai_provider import OpenAIProvider
        return OpenAIProvider()
    else:
        raise ValueError(f"Unknown LLM provider: {provider}")


def llm_identity(settings: Settings) -> tuple[str | None, str | None, str | None]:
    """(mode, provider, model) as Drupal records them on a turn.

    The CLI is mode "cli", provider "claude-cli", and the configured model or
    None for the CLI's own default. An API transport is mode "api" and its
    vendor's name.
    """
    # getattr: a test double standing in for Settings may predate these.
    provider = getattr(settings, "llm_provider", "cli")
    if provider == "cli":
        return "cli", "claude-cli", (getattr(settings, "claude_model", "") or None)
    return "api", provider, (getattr(settings, "openai_model", "") or None)
