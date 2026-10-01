"""Select an LLM provider from the LLM_PROVIDER env var."""
import os

from .base import LLMProvider


def get_provider() -> LLMProvider:
    provider = os.environ.get("LLM_PROVIDER", "bedrock").lower()

    if provider == "bedrock":
        from .bedrock import BedrockClaudeProvider

        return BedrockClaudeProvider()

    raise ValueError(f"Unknown LLM_PROVIDER: {provider!r}")
