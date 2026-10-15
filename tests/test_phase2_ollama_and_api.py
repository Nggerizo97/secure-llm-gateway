import httpx
import pytest
from fastapi.testclient import TestClient
from app.audit import AuditLogger
from app.config import Settings
from app.main import create_app
from app.policy import PolicyEngine
from app.providers.base import PolicyViolationError
from app.providers.mock import MockProvider
from app.providers.ollama import OllamaProvider
from app.router import GatewayRouter
from app.schemas import LLMRequest


def _mock_ollama_transport() -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "model": "qwen2.5-coder:7b",
                "response": "def add(a, b): return a + b",
                "prompt_eval_count": 8,
                "eval_count": 7,
            },
        )

    return httpx.MockTransport(handler)


def test_ollama_blocked_in_mock_profile():
    settings = Settings(app_profile="mock", audit_store="memory")
    audit = AuditLogger(db_path=":memory:")
    router = GatewayRouter(
        settings=settings,
        policy=PolicyEngine(settings),
        audit=audit,
        providers={
            "mock": MockProvider("mock"),
            "ollama": OllamaProvider(transport=_mock_ollama_transport()),
        },
    )
    with pytest.raises(PolicyViolationError) as exc_info:
        router.route(LLMRequest(prompt="Test local call"), primary_provider="ollama")
    assert exc_info.value.category == "provider_denied"


def test_rate_limit_fallback_to_ollama_in_local_profile():
    # Local profile's server-side route is mock -> ollama
    settings = Settings(app_profile="local", audit_store="memory")
    audit = AuditLogger(db_path=":memory:")
    router = GatewayRouter(
        settings=settings,
        policy=PolicyEngine(settings),
        audit=audit,
        providers={
            "mock": MockProvider("mock"),
            "ollama": OllamaProvider(transport=_mock_ollama_transport()),
        },
    )
    resp = router.route(
        LLMRequest(prompt="Write add function", simulate_primary="rate_limit_429")
    )
    assert resp.selected_provider == "ollama"
    assert resp.fallback_used is True
    assert resp.fallback_reason == "rate_limit"
    assert "def add" in resp.content


def test_fastapi_endpoints():
    settings = Settings(app_profile="mock", audit_store="memory")
    app = create_app(settings=settings)
    client = TestClient(app)

    # 1. Health endpoint exposes the server-side route
    health = client.get("/health")
    assert health.status_code == 200
    assert health.json()["app_profile"] == "mock"
    assert health.json()["route"] == {"primary": "mock", "fallback": "mock_fallback"}

    # 2. Generate endpoint (429 -> configured fallback)
    gen = client.post(
        "/v1/generate",
        json={"prompt": "Synthetic API test", "simulate_primary": "rate_limit_429"},
    )
    assert gen.status_code == 200
    body = gen.json()
    assert body["selected_provider"] == "mock_fallback"
    assert body["fallback_used"] is True

    # 3. Policy violation returns HTTP 403 with a server-generated request_id
    denied = client.post(
        "/v1/generate",
        json={"prompt": "Synthetic test", "model": "unapproved-gpt-5"},
    )
    assert denied.status_code == 403
    assert denied.json()["category"] == "model_denied"
    assert denied.json()["request_id"]

    # 4. Callers cannot pick providers or request IDs
    for field, value in [
        ("primary_provider", "personal_api"),
        ("fallback_provider", "ollama"),
        ("request_id", "attacker-chosen-id"),
    ]:
        rejected = client.post("/v1/generate", json={"prompt": "x", field: value})
        assert rejected.status_code == 422, field

    # 5. Audit endpoint returns metadata only; rejected (422) bodies never reach the router
    audit_resp = client.get("/v1/audit")
    assert audit_resp.status_code == 200
    assert len(audit_resp.json()) == 2
