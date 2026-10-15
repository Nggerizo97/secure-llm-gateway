from app.providers.base import PolicyViolationError, ProviderResult
from app.schemas import LLMRequest


class EnterpriseProvider:
    def __init__(self) -> None:
        self.name = "enterprise"

    def generate(self, request: LLMRequest, is_fallback: bool = False) -> ProviderResult:
        raise PolicyViolationError(
            "Enterprise provider fails closed until an approved endpoint is configured.",
            category="enterprise_unconfigured",
        )