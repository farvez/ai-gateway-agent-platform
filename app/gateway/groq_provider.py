from .openai_provider import OpenAIProvider


class GroqProvider(OpenAIProvider):
    """Groq exposes an OpenAI-compatible API, so it reuses OpenAIProvider entirely
    and only changes the name, API key, base URL and default model."""

    name = "groq"
    api_key_env = "GROQ_API_KEY"
    base_url = "https://api.groq.com/openai/v1"
    fallback_model = "openai/gpt-oss-120b"
