"""Provider registry. Add a new provider here to make it available by name."""
from app.llm.providers.openai_compat import OpenAICompatProvider

PROVIDERS = {
    "openai_compat": OpenAICompatProvider,
}

__all__ = ["PROVIDERS", "OpenAICompatProvider"]
