from typing import Optional
import httpx
from app.providers.base import (
    AuthenticationError,
    ProviderResult,
    ProviderUnavailableError,
    QuotaExhaustedError,
    RateLimitError,
)
from app.schemas import LLMRequest


class OllamaProvider:
    def __init__(
        self,
        base_url: str = "http://localhost:11434",
        default_model: str = "qwen2.5-coder:7b",
        timeout_seconds: float = 60.0,
        transport: Optional[httpx.BaseTransport] = None,
    ):
        self.name = "ollama"
        self.base_url = base_url.rstrip("/")
        self.default_model = default_model
        self.timeout_seconds = timeout_seconds
        self._transport = transport

    def generate(self, request: LLMRequest, is_fallback: bool = False) -> ProviderResult:
        model_to_use = (
            self.default_model
            if request.model.startswith("mock")
            else request.model
        )

        payload = {
            "model": model_to_use,
            "prompt": request.prompt,
            "stream": False,
        }

        try:
            with httpx.Client(timeout=self.timeout_seconds, transport=self._transport) as client:
                response = client.post(f"{self.base_url}/api/generate", json=payload)
        except httpx.RequestError as exc:
            raise ProviderUnavailableError(
                f"Ollama unreachable at {self.base_url}: {exc}"
            ) from exc

        if response.status_code == 429:
            raise RateLimitError("Ollama returned HTTP 429 rate limit")
        if response.status_code == 402:
            raise QuotaExhaustedError("Ollama returned HTTP 402 quota exhausted")
        if response.status_code in (401, 403):
            raise AuthenticationError(f"Ollama returned HTTP {response.status_code}")
        if response.status_code >= 400:
            raise ProviderUnavailableError(
                f"Ollama error HTTP {response.status_code}: {response.text[:200]}"
            )

        data = response.json()
        content = data.get("response", "").strip()
        prompt_tokens = int(data.get("prompt_eval_count") or len(request.prompt.split()))
        completion_tokens = int(data.get("eval_count") or len(content.split()))

        return ProviderResult(
            content=content,
            model=data.get("model", model_to_use),
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
        )