from typing import Optional
import httpx
from app.network_policy import assert_https_or_loopback
from app.providers.base import (
    BadProviderResponseError,
    PolicyViolationError,
    ProviderResult,
    ProviderUnavailableError,
    classify_http_error,
)
from app.schemas import LLMRequest


class OpenAICompatibleProvider:
    """Any OpenAI-compatible chat completions API (OpenAI, OpenRouter, Groq, vLLM, LM Studio, ...).

    Always sends the operator-configured model, so the approved model is decided by
    server configuration, not by the caller.
    """

    def __init__(
        self,
        base_url: str,
        api_key: Optional[str],
        model: str,
        name: str = "openai_compat",
        timeout_seconds: float = 60.0,
        transport: Optional[httpx.BaseTransport] = None,
    ):
        self.name = name
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout_seconds = timeout_seconds
        self._api_key = api_key
        self._transport = transport

    def generate(self, request: LLMRequest, is_fallback: bool = False) -> ProviderResult:
        if not (self.base_url and self.model and self._api_key):
            raise PolicyViolationError(
                f"Provider '{self.name}' is not configured (base URL, model and API key are required).",
                category="provider_unconfigured",
            )
        assert_https_or_loopback(self.base_url)

        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": request.prompt}],
        }
        headers = {"Authorization": f"Bearer {self._api_key}"}

        try:
            with httpx.Client(timeout=self.timeout_seconds, transport=self._transport) as client:
                response = client.post(f"{self.base_url}/chat/completions", json=payload, headers=headers)
        except httpx.RequestError as exc:
            raise ProviderUnavailableError(
                f"{self.name} unreachable at {self.base_url}: {type(exc).__name__}"
            ) from exc

        if response.status_code >= 400:
            raise classify_http_error(self.name, response.status_code, response.text)

        try:
            data = response.json()
            content = data["choices"][0]["message"]["content"] or ""
            usage = data.get("usage") or {}
        except (ValueError, KeyError, IndexError, TypeError, AttributeError) as exc:
            raise BadProviderResponseError(f"{self.name} returned an unexpected response body") from exc

        return ProviderResult(
            content=content.strip(),
            model=str(data.get("model") or self.model),
            prompt_tokens=int(usage.get("prompt_tokens") or len(request.prompt.split())),
            completion_tokens=int(usage.get("completion_tokens") or len(content.split())),
        )
