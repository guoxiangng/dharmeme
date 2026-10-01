"""Provider-agnostic LLM interface. Callers depend only on this."""
from dataclasses import dataclass
from typing import Any, Protocol


@dataclass
class LLMResponse:
    text: str
    refused: bool = False  # the model declined to answer (safety refusal)
    raw: Any = None


class LLMProvider(Protocol):
    def complete(self, system: str, user: str) -> LLMResponse:
        """Single-turn completion: a system prompt + a user message -> text."""
        ...
