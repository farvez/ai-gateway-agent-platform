from abc import ABC, abstractmethod
from collections.abc import Iterator


class LLMProvider(ABC):
    @abstractmethod
    def generate(self, message: str, model: str | None = None) -> dict:
        """Return the full answer at once in the normalized response shape."""

    @abstractmethod
    def stream(self, message: str, model: str | None = None) -> Iterator[dict]:
        """Yield the answer piece by piece.

        Yields {"type": "delta", "text": "..."} for each chunk of text, then exactly one
        {"type": "done", "provider": ..., "model": ..., "usage": {...}} at the end.
        """
