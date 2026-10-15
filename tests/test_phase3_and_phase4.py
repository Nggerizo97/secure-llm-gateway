from pathlib import Path
import pytest
from app.audit import AuditLogger
from app.config import Settings
from app.policy import PolicyEngine
from app.providers.base import PolicyViolationError, QuotaExhaustedError
from app.providers.mock import MockProvider
from app.retrieval.chroma_store import is_safe_sample_file
from app.retrieval.interface import RetrievedChunk
from app.router import GatewayRouter
from app.schemas import LLMRequest


class FakeRetrievalStore:
    def index_directory(self, root_dir: str) -> int:
        return 1

    def query(self, prompt: str, top_k: int = 2) -> list[RetrievedChunk]:
        return [
            RetrievedChunk(
                source_path="retry_helper.py",
                content="def compute_backoff_seconds(attempt: int): ...",
            )
        ]


def test_model_allowlist_denies_unapproved_model():
    settings = Settings(app_profile="mock", audit_store="memory")
    router = GatewayRouter(
        settings=settings,
        policy=PolicyEngine(settings),
        audit=AuditLogger(":memory:"),
        providers={"mock": MockProvider("mock")},
    )
    with pytest.raises(PolicyViolationError) as exc_info:
        router.route(LLMRequest(prompt="Hello", model="unapproved-gpt-5"))
    assert exc_info.value.category == "model_denied"


def test_no_fallback_on_quota_exhausted_402():
    settings = Settings(app_profile="mock", audit_store="memory")
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
    with pytest.raises(QuotaExhaustedError):
        router.route(
            LLMRequest(
                prompt="Test quota boundary",
                simulate_primary="quota_exceeded_402",
            )
        )
    events = audit.list_events()
    assert len(events) == 1
    assert events[0].status_category == "quota_exhausted"
    assert events[0].fallback_used is False


def test_audit_metrics_computation():
    settings = Settings(app_profile="mock", audit_store="memory")
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
    router.route(LLMRequest(prompt="Normal request"))
    router.route(
        LLMRequest(
            prompt="Rate limited request",
            simulate_primary="rate_limit_429",
        )
    )
    metrics = audit.compute_metrics()
    assert metrics["total_recorded_requests"] == 2
    assert metrics["rate_limit_events_total"] == 1
    assert metrics["rate_limit_fallback_recovery_pct"] == 100.0
    assert metrics["prompt_or_output_columns_in_db"] == 0


def test_rag_file_filter_excludes_secrets_and_dotenv(tmp_path: Path):
    safe_py = tmp_path / "helper.py"
    safe_py.write_text("def ok(): pass", encoding="utf-8")

    dotenv_file = tmp_path / ".env"
    dotenv_file.write_text("SECRET=123", encoding="utf-8")

    private_key = tmp_path / "id_rsa.pem"
    private_key.write_text("PRIVATE KEY", encoding="utf-8")

    assert is_safe_sample_file(safe_py) is True
    assert is_safe_sample_file(dotenv_file) is False
    assert is_safe_sample_file(private_key) is False


def test_optional_rag_augments_context_when_enabled():
    settings = Settings(app_profile="mock", enable_rag=True, audit_store="memory")
    router = GatewayRouter(
        settings=settings,
        policy=PolicyEngine(settings),
        audit=AuditLogger(":memory:"),
        providers={"mock": MockProvider("mock")},
        retrieval_store=FakeRetrievalStore(),
    )
    resp = router.route(LLMRequest(prompt="Explain backoff", use_rag=True))
    assert len(resp.retrieved_chunks) == 1
    assert "retry_helper.py" in resp.retrieved_chunks[0]