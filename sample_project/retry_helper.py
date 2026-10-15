"""Synthetic sample module for Secure LLM Gateway RAG demonstration."""


def compute_backoff_seconds(attempt: int, base_delay: float = 0.5, max_delay: float = 8.0) -> float:
    """Calculate capped exponential backoff delay for retryable HTTP 429 responses."""
    if attempt < 0:
        raise ValueError("attempt must be non-negative")
    delay = base_delay * (2 ** attempt)
    return min(delay, max_delay)