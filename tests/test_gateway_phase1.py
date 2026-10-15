import pytest
from app.audit import AuditLogger
from app.config import Settings
from app.policy import PolicyEngine
from app.providers.base import AuthenticationError, PolicyViolationError
from app.providers.mock import MockProvider
from app.router import GatewayRouter
from app.schemas import LLMRequest


@pytest.fixture
def gateway() -> tuple[GatewayRouter, AuditLogger]:
    settings = Settings(app_profile="mock", enable_rag=False, audit_db_path=":memory:")
    audit = AuditLogger(db_path=":memory:")
    policy = PolicyEngine(settings=settings)
    router = GatewayRouter(
        settings=settings,
        policy=policy,
        audit=audit,
        providers={
            "mock": MockProvider(name="mock"),
            "mock_fallback": MockProvider(name="mock_fallback"),
        },
    )
    return router, audit


def test_primary_success(gateway):
    router, _ = gateway
    resp = router.route(LLMRequest(prompt="Synthetic test prompt"))
    assert resp.selected_provider == "mock"
    assert resp.fallback_used is False
    assert resp.fallback_reason is None


def test_rate_limit_fallback(gateway):
    router, _ = gateway
    resp = router.route(
        LLMRequest(
            prompt="Synthetic test prompt",
            simulate_primary="rate_limit_429",
        )
    )
    assert resp.selected_provider == "mock_fallback"
    assert resp.fallback_used is True
    assert resp.fallback_reason == "rate_limit"


def test_no_fallback_on_auth_error(gateway):
    router, audit = gateway
    with pytest.raises(AuthenticationError):
        router.route(
            LLMRequest(
                prompt="Synthetic test prompt",
                simulate_primary="auth_error_401",
            )
        )
    events = audit.list_events()
    assert len(events) == 1
    assert events[0].status_category == "auth_error"
    assert events[0].fallback_used is False
    assert events[0].selected_provider == "none"


def test_policy_denies_unapproved_provider_and_secrets(gateway):
    router, _ = gateway
    # Deny personal_api
    with pytest.raises(PolicyViolationError) as exc_info:
        router.route(LLMRequest(prompt="Hello"), primary_provider="personal_api")
    assert exc_info.value.category == "provider_denied"

    # Deny fallback to unapproved provider on 429, even via operator override
    with pytest.raises(PolicyViolationError):
        router.route(
            LLMRequest(prompt="Hello", simulate_primary="rate_limit_429"),
            fallback_provider="personal_api",
        )

    # Deny leaked secret in prompt
    with pytest.raises(PolicyViolationError) as secret_exc:
        router.route(LLMRequest(prompt="Here is my key sk-1234567890abcdef123456"))
    assert secret_exc.value.category == "secret_detected"


def test_no_prompt_logging(gateway):
    router, audit = gateway
    sensitive_marker = "UNIQUE_SYNTHETIC_SECRET_MARKER_998877"
    resp = router.route(LLMRequest(prompt=f"Analyze {sensitive_marker}"))

    raw_db = audit.dump_raw_database_text()
    assert sensitive_marker not in raw_db
    assert resp.content not in raw_db


def test_rag_is_optional_and_disabled_by_default(gateway):
    router, _ = gateway
    with pytest.raises(PolicyViolationError) as exc_info:
        router.route(LLMRequest(prompt="Query sample repo", use_rag=True))
    assert exc_info.value.category == "rag_disabled"