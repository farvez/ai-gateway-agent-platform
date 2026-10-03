from abc import ABC, abstractmethod


class LLMProvider(ABC):
    @abstractmethod
    def generate(self, message: str, model: str | None = None) -> dict:
        pass
