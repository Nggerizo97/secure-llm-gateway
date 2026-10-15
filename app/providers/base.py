from typing import Optional, Protocol
from app.schemas import LLMRequest


class ProviderResult:
    def __init__(self, content: str, model: str, prompt_tokens: int, completion_tokens: int):
        self.content = content
        self.model = model
        self.prompt_tokens = prompt_tokens
        self.completion_tokens = completion_tokens


class GatewayError(Exception):
    def __init__(self, message: str, status_code: int, category: str, retryable: bool):
        super().__init__(message)
        self.status_code = status_code
        self.category = category
        self.retryable = retryable
        self.request_id: Optional[str] = None  # set by the router for traceability


class RateLimitError(GatewayError):
    def __init__(self, message: str = "Primary provider HTTP 429 rate limit exceeded"):
        super().__init__(message, status_code=429, category="rate_limit", retryable=True)


class ProviderUnavailableError(GatewayError):
    def __init__(self, message: str = "Provider HTTP 503 temporarily unavailable"):
        super().__init__(message, status_code=503, category="service_unavailable", retryable=True)


class AuthenticationError(GatewayError):
    def __init__(self, message: str = "Provider HTTP 401/403 authentication failed"):
        super().__init__(message, status_code=401, category="auth_error", retryable=False)


class QuotaExhaustedError(GatewayError):
    def __init__(self, message: str = "Provider HTTP 402 quota exhausted"):
        super().__init__(message, status_code=402, category="quota_exhausted", retryable=False)


class PolicyViolationError(GatewayError):
    def __init__(self, message: str, category: str = "policy_denied"):
        super().__init__(message, status_code=403, category=category, retryable=False)


class LLMProvider(Protocol):
    name: str

    def generate(self, request: LLMRequest, is_fallback: bool = False) -> ProviderResult:
        ...