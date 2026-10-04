# USD per 1 million tokens: (input, output).
# Sources (checked 2026-10-05): OpenAI developers.openai.com/api/docs/pricing,
# Groq console.groq.com/docs/models, Anthropic platform pricing.
# Providers change prices, so re-check these when you add or switch models.
PRICES_PER_MILLION: dict[str, tuple[float, float]] = {
    # OpenAI
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4o": (2.50, 10.00),
    # Anthropic
    "claude-opus-5-5": (4.00, 20.00),
    "claude-sonnet-5-5": (2.00, 10.00),
    "claude-sonnet-5": (2.00, 10.00),
    "claude-haiku-4-5": (1.00, 5.00),
    # Groq
    "openai/gpt-oss-120b": (0.15, 0.60),
    "openai/gpt-oss-20b": (0.075, 0.30),
    "qwen/qwen3.8-27b": (0.80, 4.00),
}


def cost_usd(model: str | None, input_tokens: int, output_tokens: int) -> float | None:
    """Cost of one request in USD, or None if the model has no known price."""
    if model not in PRICES_PER_MILLION:
        return None

    input_price, output_price = PRICES_PER_MILLION[model]
    cost = input_tokens * input_price / 1_000_000 + output_tokens * output_price / 1_000_000
    return round(cost, 8)
