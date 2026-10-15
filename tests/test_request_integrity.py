import sqlite3
import pytest
from pydantic import ValidationError
from app.audit import AuditLogger
from app.config import Settings
from app.policy import PolicyEngine
from app.providers.base import PolicyViolationError, RateLimitError
from app.providers.mock import MockProvider
from app.router import GatewayRouter
from app.schemas import LLMRequest


def _router(settings: Settings) -> tuple[GatewayRouter, AuditLogger]:
    audit = AuditLogger(":memory:")
    router = GatewayRouter(
        settings=settings,
        policy=PolicyEngine(settings),
        audit=audit,
        providers={
            "mock": MockProvider("mock"),
            "mock_fallback": MockProvider("mock_fallback"),
        },
    )
    return router, audit


def test_simulation_disabled_blocks_forced_fallback():
    router, audit = _router(Settings(app_profile="mock", allow_simulation=False))
    with pytest.raises(PolicyViolationError) as exc_info:
        router.route(LLMRequest(prompt="Force a fallback", simulate_primary="rate_limit_429"))
    assert exc_info.value.category == "simulation_disabled"

    events = audit.list_events()
    assert len(events) == 1
    assert events[0].fallback_used is False
    assert events[0].selected_provider == "none"


def test_simulation_off_by_default_and_unenableable_in_enterprise():
    assert Settings(app_profile="enterprise").allow_simulation is False
    with pytest.raises(ValidationError):
        Settings(app_profile="enterprise", allow_simulation=True)


def test_routes_come_from_server_config():
    assert Settings(app_profile="mock").fallback_provider == "mock_fallback"
    assert Settings(app_profile="local").fallback_provider == "ollama"
    assert Settings(app_profile="enterprise").fallback_provider is None
    assert Settings(app_profile="mock", fallback_provider="none").fallback_provider is None


def test_fallback_disabled_by_config_does_not_reroute():
    router, audit = _router(Settings(app_profile="mock", fallback_provider="none"))
    with pytest.raises(RateLimitError):
        router.route(LLMRequest(prompt="No fallback", simulate_primary="rate_limit_429"))
    assert audit.list_events()[0].status_category == "rate_limit"


def test_env_route_overrides(monkeypatch):
    monkeypatch.setenv("APP_PROFILE", "mock")
    monkeypatch.setenv("FALLBACK_PROVIDER", "none")
    monkeypatch.setenv("ALLOW_SIMULATION", "false")
    settings = Settings.from_env()
    assert settings.primary_provider == "mock"
    assert settings.fallback_provider is None
    assert settings.allow_simulation is False


@pytest.mark.parametrize("field", ["request_id", "primary_provider", "fallback_provider"])
def test_request_rejects_client_controlled_routing_fields(field):
    with pytest.raises(ValidationError):
        LLMRequest(prompt="x", **{field: "client-value"})


def test_request_ids_are_server_generated_and_audit_is_insert_only():
    router, audit = _router(Settings(app_profile="mock"))
    first = router.route(LLMRequest(prompt="One"))
    second = router.route(LLMRequest(prompt="Two"))
    assert first.request_id != second.request_id
    assert len(audit.list_events()) == 2

    # A duplicate ID can no longer overwrite an existing audit row
    existing = audit.list_events(limit=1)[0]
    with pytest.raises(sqlite3.IntegrityError):
        audit.record(existing.model_copy(update={"status_category": "tampered"}))
    assert all(e.status_category != "tampered" for e in audit.list_events())


def test_errors_carry_the_audited_request_id():
    router, audit = _router(Settings(app_profile="mock"))
    with pytest.raises(PolicyViolationError) as exc_info:
        router.route(LLMRequest(prompt="x", model="unapproved"))
    assert exc_info.value.request_id == audit.list_events()[0].request_id
