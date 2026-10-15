from app.providers.base import ProviderResult
from app.schemas import LLMRequest


class MockProvider:
    def __init__(self, name: str = "mock"):
        self.name = name

    def generate(self, request: LLMRequest, is_fallback: bool = False) -> ProviderResult:
        role_label = "FALLBACK" if is_fallback else "PRIMARY"
        content = f"[{self.name}:{role_label}] Deterministic synthetic response for model '{request.model}'."
        prompt_tokens = max(1, len(request.prompt.split()))
        completion_tokens = len(content.split())

        return ProviderResult(
            content=content,
            model=request.model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
        )
