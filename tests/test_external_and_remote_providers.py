"""Real (HTTP-level) fallback and remote-model security. All HTTP goes to in-process fake transports."""

import socket
from typing import Callable, List, Optional
import httpx
import pytest
from app.audit import AuditLogger
from app.config import Settings
from app.policy import PolicyEngine
from app.providers.base import (
    AuthenticationError,
    GatewayError,
    PolicyViolationError,
    QuotaExhaustedError,
)
from app.providers.ollama import OllamaProvider
from app.providers.openai_compat import OpenAICompatibleProvider
from app.router import GatewayRouter
from app.schemas import LLMRequest

FAKE_KEY = "test-key-not-a-real-secret"
TOKEN = "test-proxy-token"


def _transport(status: int, body, seen: Optional[List[httpx.Request]] = None) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(request)
        if isinstance(body, str):
            return httpx.Response(status, text=body)
        return httpx.Response(status, json=body)

    return httpx.MockTransport(handler)


def _chat_ok(content: str = "def add(a, b): return a + b") -> dict:
    return {
        "model": "gpt-test",
        "choices": [{"message": {"role": "assistant", "content": content}}],
        "usage": {"prompt_tokens": 5, "completion_tokens": 9},
    }


def _ollama_ok() -> dict:
    return {"model": "qwen2.5-coder:7b", "response": "local answer", "prompt_eval_count": 4, "eval_count": 2}


def _external(status: int, body, seen=None, **overrides) -> OpenAICompatibleProvider:
    kwargs = dict(base_url="https://api.example.test/v1", api_key=FAKE_KEY, model="gpt-test")
    kwargs.update(overrides)
    return OpenAICompatibleProvider(transport=_transport(status, body, seen), **kwargs)


def _gateway(primary, fallback=None, **settings_overrides) -> tuple[GatewayRouter, AuditLogger]:
    settings = Settings(
        app_profile="local",
        audit_store="memory",
        primary_provider="openai_compat",
        fallback_provider="ollama" if fallback else "none",
        **settings_overrides,
    )
    audit = AuditLogger(":memory:")
    providers = {"openai_compat": primary}
    if fallback:
        providers["ollama"] = fallback
    router = GatewayRouter(settings=settings, policy=PolicyEngine(settings), audit=audit, providers=providers)
    return router, audit


# --- External provider ------------------------------------------------------------------


def test_external_provider_success_sends_key_and_configured_model():
    seen: List[httpx.Request] = []
    router, _ = _gateway(_external(200, _chat_ok(), seen))
    resp = router.route(LLMRequest(prompt="Write add"))

    assert resp.selected_provider == "openai_compat"
    assert "def add" in resp.content
    assert (resp.prompt_tokens, resp.completion_tokens) == (5, 9)
    assert str(seen[0].url) == "https://api.example.test/v1/chat/completions"
    assert seen[0].headers["Authorization"] == f"Bearer {FAKE_KEY}"
    assert b'"model":"gpt-test"' in seen[0].content.replace(b" ", b"")


def test_real_http_429_falls_back_to_remote_model():
    """The core requirement: company provider out of tokens -> approved self-hosted model."""
    fallback = OllamaProvider(
        base_url="https://10.0.0.5:11434", api_key=TOKEN, transport=_transport(200, _ollama_ok())
    )
    router, audit = _gateway(
        _external(429, {"error": {"code": "rate_limit_exceeded", "message": "TPM limit"}}), fallback
    )
    resp = router.route(LLMRequest(prompt="Explain this function"))

    assert resp.selected_provider == "ollama"
    assert resp.fallback_reason == "rate_limit"
    assert audit.list_events()[0].status_category == "fallback_success"


def test_quota_exhausted_does_not_fall_back_by_default():
    fallback = OllamaProvider(transport=_transport(200, _ollama_ok()))
    router, audit = _gateway(
        _external(429, {"error": {"code": "insufficient_quota", "message": "out of credits"}}), fallback
    )
    with pytest.raises(QuotaExhaustedError):
        router.route(LLMRequest(prompt="x"))
    assert audit.list_events()[0].fallback_used is False


def test_quota_exhausted_falls_back_when_alternative_budget_approved():
    fallback = OllamaProvider(transport=_transport(200, _ollama_ok()))
    router, _ = _gateway(
        _external(429, {"error": {"code": "insufficient_quota"}}), fallback, fallback_on_quota_exhausted=True
    )
    resp = router.route(LLMRequest(prompt="x"))
    assert resp.selected_provider == "ollama"
    assert resp.fallback_reason == "quota_exhausted"


@pytest.mark.parametrize(
    ("status", "body", "expected"),
    [
        (401, {"error": "bad key"}, AuthenticationError),
        (400, {"error": "content policy violation"}, GatewayError),
        (200, "not json", GatewayError),
        (200, {"unexpected": "shape"}, GatewayError),
    ],
)
def test_non_capacity_errors_never_reroute(status, body, expected):
    seen: List[httpx.Request] = []
    fallback = OllamaProvider(transport=_transport(200, _ollama_ok(), seen))
    router, audit = _gateway(_external(status, body), fallback)
    with pytest.raises(expected) as exc_info:
        router.route(LLMRequest(prompt="x"))
    assert exc_info.value.retryable is False
    assert seen == []  # fallback model was never contacted
    assert audit.list_events()[0].fallback_used is False


def test_upstream_error_body_is_not_echoed():
    router, _ = _gateway(_external(400, {"error": "prompt contained SECRET_MARKER_123"}))
    with pytest.raises(GatewayError) as exc_info:
        router.route(LLMRequest(prompt="x"))
    assert "SECRET_MARKER_123" not in str(exc_info.value)


@pytest.mark.parametrize(
    ("overrides", "category"),
    [
        ({"api_key": None}, "provider_unconfigured"),
        ({"model": ""}, "provider_unconfigured"),
        ({"base_url": "http://api.example.test/v1"}, "endpoint_denied"),
    ],
)
def test_external_provider_fails_closed_when_misconfigured(overrides, category):
    seen: List[httpx.Request] = []
    router, _ = _gateway(_external(200, _chat_ok(), seen, **overrides))
    with pytest.raises(PolicyViolationError) as exc_info:
        router.route(LLMRequest(prompt="x"))
    assert exc_info.value.category == category
    assert seen == []


def test_external_provider_blocked_in_mock_profile():
    settings = Settings(app_profile="mock", audit_store="memory")
    router = GatewayRouter(
        settings=settings,
        policy=PolicyEngine(settings),
        audit=AuditLogger(":memory:"),
        providers={"openai_compat": _external(200, _chat_ok())},
    )
    with pytest.raises(PolicyViolationError) as exc_info:
        router.route(LLMRequest(prompt="x"), primary_provider="openai_compat")
    assert exc_info.value.category == "provider_denied"


def test_api_keys_never_appear_in_settings_repr_or_audit():
    settings = Settings(app_profile="local", openai_compat_api_key=FAKE_KEY, ollama_api_key=TOKEN)
    assert FAKE_KEY not in repr(settings) and TOKEN not in repr(settings)

    router, audit = _gateway(_external(200, _chat_ok()))
    router.route(LLMRequest(prompt="x"))
    assert FAKE_KEY not in audit.dump_raw_database_text()


# --- Remote self-hosted model -----------------------------------------------------------


def _ollama_call(base_url: str, **kwargs) -> Callable[[], object]:
    seen: List[httpx.Request] = []
    provider = OllamaProvider(base_url=base_url, transport=_transport(200, _ollama_ok(), seen), **kwargs)
    return lambda: (provider.generate(LLMRequest(prompt="x")), seen)


@pytest.mark.parametrize(
    "base_url",
    [
        "http://localhost:11434",
        "http://127.0.0.1:11434",
    ],
)
def test_ollama_on_same_machine_needs_no_token(base_url):
    result, seen = _ollama_call(base_url)()
    assert len(seen) == 1
    assert "Authorization" not in seen[0].headers


def test_remote_ollama_over_https_with_token_sends_bearer():
    _, seen = _ollama_call("https://192.168.1.20:11434", api_key=TOKEN)()
    assert seen[0].headers["Authorization"] == f"Bearer {TOKEN}"


def test_remote_ollama_plain_http_allowed_only_when_tunnel_confirmed():
    _, seen = _ollama_call("http://100.101.1.2:11434", api_key=TOKEN, allow_plaintext_tunnel=True)()
    assert len(seen) == 1


@pytest.mark.parametrize(
    ("base_url", "kwargs", "reason"),
    [
        ("https://8.8.8.8:11434", {"api_key": TOKEN}, "public"),
        ("https://0.0.0.0:11434", {"api_key": TOKEN}, "non-routable"),
        ("https://169.254.10.10:11434", {"api_key": TOKEN}, "non-routable"),
        ("https://10.0.0.5:11434", {}, "API key"),
        ("http://10.0.0.5:11434", {"api_key": TOKEN}, "https"),
        ("ftp://10.0.0.5", {"api_key": TOKEN}, "valid"),
    ],
)
def test_remote_ollama_denied_without_private_network_token_and_tls(base_url, kwargs, reason):
    call = _ollama_call(base_url, **kwargs)
    with pytest.raises(PolicyViolationError) as exc_info:
        call()
    assert exc_info.value.category == "endpoint_denied"
    assert reason in str(exc_info.value)


def test_remote_ollama_hostnames_are_resolved_before_trusting(monkeypatch):
    fake_dns = {"model-server.tailnet.test": "100.101.1.2", "evil.example.test": "93.184.216.34"}

    def fake_getaddrinfo(host, *args, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (fake_dns[host], 0))]

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)

    _, seen = _ollama_call("https://model-server.tailnet.test:11434", api_key=TOKEN)()
    assert len(seen) == 1

    with pytest.raises(PolicyViolationError):
        _ollama_call("https://evil.example.test:11434", api_key=TOKEN)()


def test_denied_remote_fallback_is_audited_and_not_contacted():
    seen: List[httpx.Request] = []
    public_fallback = OllamaProvider(
        base_url="https://8.8.8.8:11434", api_key=TOKEN, transport=_transport(200, _ollama_ok(), seen)
    )
    router, audit = _gateway(_external(429, {"error": {"code": "rate_limit_exceeded"}}), public_fallback)
    with pytest.raises(PolicyViolationError):
        router.route(LLMRequest(prompt="x"))
    assert seen == []
    assert audit.list_events()[0].status_category == "fallback_failed:endpoint_denied"
