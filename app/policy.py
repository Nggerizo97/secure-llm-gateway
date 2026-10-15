import re
from app.config import Settings
from app.providers.base import PolicyViolationError
from app.schemas import LLMRequest

ALLOWED_PROVIDERS_BY_PROFILE: dict[str, set[str]] = {
    "mock": {"mock", "mock_fallback"},
    "local": {"mock", "mock_fallback", "ollama"},
    "enterprise": set(),
}

ALLOWED_MODELS_BY_PROFILE: dict[str, set[str]] = {
    "mock": {"mock-coder-v1", "mock-fast-v1"},
    "local": {"mock-coder-v1", "mock-fast-v1", "qwen2.5-coder:7b", "qwen2.5-coder:1.5b", "llama3.2:3b"},
    "enterprise": set(),
}

SECRET_PATTERNS = [
    re.compile(r"sk-[a-zA-Z0-9]{16,}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"-----BEGIN (RSA|EC|OPENSSH|PRIVATE) KEY-----"),
    re.compile(r"gh[pousr]_[A-Za-z0-9_]{20,}"),
]


class PolicyEngine:
    def __init__(self, settings: Settings):
        self.settings = settings

    def validate_request(self, request: LLMRequest, primary_provider: str) -> None:
        if self.settings.app_profile in {"mock", "local"} and request.data_classification != "synthetic":
            raise PolicyViolationError(
                f"Data classification '{request.data_classification}' is not permitted in '{self.settings.app_profile}' profile.",
                category="data_classification_denied",
            )

        simulating = request.simulate_primary != "ok" or request.simulate_fallback != "ok"
        if simulating and not self.settings.allow_simulation:
            raise PolicyViolationError(
                f"Fault simulation is disabled in profile '{self.settings.app_profile}'.",
                category="simulation_disabled",
            )

        self.assert_provider_allowed(primary_provider)
        self.assert_model_allowed(request.model)

        if request.use_rag and not self.settings.enable_rag:
            raise PolicyViolationError(
                "Retrieval (RAG) requested but ENABLE_RAG is false by policy.",
                category="rag_disabled",
            )

        for pattern in SECRET_PATTERNS:
            if pattern.search(request.prompt):
                raise PolicyViolationError(
                    "Request blocked: potential credential or secret detected in prompt.",
                    category="secret_detected",
                )

    def assert_provider_allowed(self, provider_name: str) -> None:
        if provider_name == "personal_api":
            raise PolicyViolationError(
                "Provider 'personal_api' is strictly prohibited by gateway policy.",
                category="provider_denied",
            )

        allowed = ALLOWED_PROVIDERS_BY_PROFILE.get(self.settings.app_profile, set())
        if provider_name not in allowed:
            raise PolicyViolationError(
                f"Provider '{provider_name}' is not allowed in profile '{self.settings.app_profile}'.",
                category="provider_denied",
            )

    def assert_model_allowed(self, model_name: str) -> None:
        allowed_models = set(ALLOWED_MODELS_BY_PROFILE.get(self.settings.app_profile, set()))
        if self.settings.app_profile == "local":
            allowed_models.add(self.settings.ollama_model)

        if model_name not in allowed_models:
            raise PolicyViolationError(
                f"Model '{model_name}' is not allowlisted for profile '{self.settings.app_profile}'.",
                category="model_denied",
            )