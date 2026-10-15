import ssl
from typing import Optional
import httpx
from app.network_policy import assert_private_model_endpoint
from app.providers.base import (
    BadProviderResponseError,
    ProviderResult,
    ProviderUnavailableError,
    classify_http_error,
)
from app.schemas import LLMRequest


class OllamaProvider:
    """Self-hosted model via the Ollama API, on this machine or a remote server over a private network."""

    def __init__(
        self,
        base_url: str = "http://localhost:11434",
        default_model: str = "qwen2.5-coder:7b",
        timeout_seconds: float = 60.0,
        transport: Optional[httpx.BaseTransport] = None,
        api_key: Optional[str] = None,
        ca_bundle: Optional[str] = None,
        allow_plaintext_tunnel: bool = False,
    ):
        self.name = "ollama"
        self.base_url = base_url.rstrip("/")
        self.default_model = default_model
        self.timeout_seconds = timeout_seconds
        self._transport = transport
        self._api_key = api_key
        self._ca_bundle = ca_bundle
        self._allow_plaintext_tunnel = allow_plaintext_tunnel

    def generate(self, request: LLMRequest, is_fallback: bool = False) -> ProviderResult:
        assert_private_model_endpoint(
            self.base_url,
            has_api_key=bool(self._api_key),
            allow_plaintext_tunnel=self._allow_plaintext_tunnel,
        )

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
        headers = {"Authorization": f"Bearer {self._api_key}"} if self._api_key else {}
        verify = ssl.create_default_context(cafile=self._ca_bundle) if self._ca_bundle else True

        try:
            with httpx.Client(
                timeout=self.timeout_seconds, transport=self._transport, verify=verify
            ) as client:
                response = client.post(f"{self.base_url}/api/generate", json=payload, headers=headers)
        except httpx.RequestError as exc:
            raise ProviderUnavailableError(
                f"Ollama unreachable at {self.base_url}: {type(exc).__name__}"
            ) from exc

        if response.status_code >= 400:
            raise classify_http_error("ollama", response.status_code, response.text)

        try:
            data = response.json()
            content = str(data.get("response", "")).strip()
        except (ValueError, AttributeError) as exc:
            raise BadProviderResponseError("Ollama returned an unexpected response body") from exc
        prompt_tokens = int(data.get("prompt_eval_count") or len(request.prompt.split()))
        completion_tokens = int(data.get("eval_count") or len(content.split()))

        return ProviderResult(
            content=content,
            model=data.get("model", model_to_use),
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
        )
