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
