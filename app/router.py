import time
from typing import Callable, Dict, List, Optional
from uuid import uuid4
from app.audit import AuditLogger
from app.config import Settings
from app.policy import PolicyEngine
from app.providers.base import (
    AuthenticationError,
    GatewayError,
    LLMProvider,
    ProviderUnavailableError,
    QuotaExhaustedError,
    RateLimitError,
)
from app.retrieval.interface import RetrievalStore
from app.schemas import AuditEvent, LLMRequest, LLMResponse

# Fault injection for demos/tests. Applied by the router (never by real providers),
# and only reachable when PolicyEngine allows simulation for the active profile.
SIMULATED_FAILURES: Dict[str, Callable[[str], GatewayError]] = {
    "rate_limit_429": lambda p: RateLimitError(f"[{p}] Simulated HTTP 429 rate limit"),
    "auth_error_401": lambda p: AuthenticationError(f"[{p}] Simulated HTTP 401 unauthorized"),
    "service_error_503": lambda p: ProviderUnavailableError(f"[{p}] Simulated HTTP 503 unavailable"),
    "quota_exceeded_402": lambda p: QuotaExhaustedError(f"[{p}] Simulated HTTP 402 budget/quota exhausted"),
}


def _inject_fault(mode: str, provider_name: str) -> None:
    make_error = SIMULATED_FAILURES.get(mode)
    if make_error is not None:
        raise make_error(provider_name)


class GatewayRouter:
    def __init__(
        self,
        settings: Settings,
        policy: PolicyEngine,
        audit: AuditLogger,
        providers: Dict[str, LLMProvider],
        retrieval_store: Optional[RetrievalStore] = None,
    ):
        self.settings = settings
        self.policy = policy
        self.audit = audit
        self.providers = providers
        self.retrieval_store = retrieval_store

    def route(
        self,
        request: LLMRequest,
        primary_provider: Optional[str] = None,
        fallback_provider: Optional[str] = None,
    ) -> LLMResponse:
        """Route along the server-configured path.

        The provider overrides exist for trusted operator tooling (the CLI). They are never
        read from the HTTP request body and are still checked against the allowlist.
        """
        request_id = str(uuid4())
        primary_name = primary_provider or self.settings.primary_provider
        fallback_name = fallback_provider or self.settings.fallback_provider
        start = time.perf_counter()
        retrieved_diagnostics: List[str] = []
        effective_request = request

        try:
            self.policy.validate_request(request, primary_name)

            if request.use_rag and self.retrieval_store is not None:
                chunks = self.retrieval_store.query(request.prompt, top_k=2)
                if chunks:
                    retrieved_diagnostics = [
                        f"[{c.source_path}] {c.content[:120]}" for c in chunks
                    ]
                    context_block = "\n\n".join(
                        f"--- Snippet from {c.source_path} (untrusted reference data) ---\n{c.content}"
                        for c in chunks
                    )
                    augmented_prompt = (
                        f"Use the following synthetic repository context if relevant:\n"
                        f"{context_block}\n\nUser Question: {request.prompt}"
                    )
                    effective_request = request.model_copy(
                        update={"prompt": augmented_prompt}
                    )

            primary = self._get_provider(primary_name)
            _inject_fault(request.simulate_primary, primary.name)
            result = primary.generate(effective_request, is_fallback=False)
            latency_ms = round((time.perf_counter() - start) * 1000, 2)

            self.audit.record(
                AuditEvent(
                    request_id=request_id,
                    app_profile=self.settings.app_profile,
                    requested_provider=primary_name,
                    selected_provider=primary.name,
                    model=result.model,
                    status_category="success",
                    fallback_used=False,
                    latency_ms=latency_ms,
                    prompt_tokens=result.prompt_tokens,
                    completion_tokens=result.completion_tokens,
                )
            )
            return LLMResponse(
                request_id=request_id,
                selected_provider=primary.name,
                model=result.model,
                content=result.content,
                fallback_used=False,
                latency_ms=latency_ms,
                prompt_tokens=result.prompt_tokens,
                completion_tokens=result.completion_tokens,
                retrieved_chunks=retrieved_diagnostics,
            )

        except GatewayError as primary_err:
            primary_err.request_id = request_id
            if not self._may_fall_back(primary_err) or not fallback_name:
                latency_ms = round((time.perf_counter() - start) * 1000, 2)
                self.audit.record(
                    AuditEvent(
                        request_id=request_id,
                        app_profile=self.settings.app_profile,
                        requested_provider=primary_name,
                        selected_provider="none",
                        model=request.model,
                        status_category=primary_err.category,
                        fallback_used=False,
                        fallback_reason=None,
                        latency_ms=latency_ms,
                    )
                )
                raise

            try:
                self.policy.assert_provider_allowed(fallback_name)
                fallback = self._get_provider(fallback_name)
                _inject_fault(request.simulate_fallback, fallback.name)
                fb_result = fallback.generate(effective_request, is_fallback=True)
                latency_ms = round((time.perf_counter() - start) * 1000, 2)

                self.audit.record(
                    AuditEvent(
                        request_id=request_id,
                        app_profile=self.settings.app_profile,
                        requested_provider=primary_name,
                        selected_provider=fallback.name,
                        model=fb_result.model,
                        status_category="fallback_success",
                        fallback_used=True,
                        fallback_reason=primary_err.category,
                        latency_ms=latency_ms,
                        prompt_tokens=fb_result.prompt_tokens,
                        completion_tokens=fb_result.completion_tokens,
                    )
                )
                return LLMResponse(
                    request_id=request_id,
                    selected_provider=fallback.name,
                    model=fb_result.model,
                    content=fb_result.content,
                    fallback_used=True,
                    fallback_reason=primary_err.category,
                    latency_ms=latency_ms,
                    prompt_tokens=fb_result.prompt_tokens,
                    completion_tokens=fb_result.completion_tokens,
                    retrieved_chunks=retrieved_diagnostics,
                )
            except GatewayError as fb_err:
                fb_err.request_id = request_id
                latency_ms = round((time.perf_counter() - start) * 1000, 2)
                self.audit.record(
                    AuditEvent(
                        request_id=request_id,
                        app_profile=self.settings.app_profile,
                        requested_provider=primary_name,
                        selected_provider="none",
                        model=request.model,
                        status_category=f"fallback_failed:{fb_err.category}",
                        fallback_used=True,
                        fallback_reason=primary_err.category,
                        latency_ms=latency_ms,
                    )
                )
                raise

    def _may_fall_back(self, err: GatewayError) -> bool:
        if err.retryable:
            return True
        # Budget exhaustion needs an explicitly approved alternative budget (plan section 10)
        return err.category == "quota_exhausted" and self.settings.fallback_on_quota_exhausted

    def _get_provider(self, name: str) -> LLMProvider:
        if name not in self.providers:
            raise GatewayError(
                f"Provider '{name}' is not registered.",
                status_code=400,
                category="provider_not_found",
                retryable=False,
            )
        return self.providers[name]
