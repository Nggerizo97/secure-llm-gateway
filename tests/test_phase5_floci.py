import httpx
import pytest
from app.config import Settings
from app.floci_exporter import FlociAuditExporter
from app.providers.base import PolicyViolationError
from app.schemas import AuditEvent


def _mock_floci_transport(recorded_urls: list[str]) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        recorded_urls.append(str(request.url))
        return httpx.Response(200, text="OK")

    return httpx.MockTransport(handler)


def _sample_audit_event() -> AuditEvent:
    return AuditEvent(
        request_id="req-synthetic-001",
        app_profile="local",
        requested_provider="mock",
        selected_provider="mock",
        model="mock-coder-v1",
        status_category="success",
        fallback_used=False,
        latency_ms=1.25,
        prompt_tokens=6,
        completion_tokens=8,
    )


def test_floci_disabled_by_default():
    settings = Settings(app_profile="local", enable_floci=False)
    exporter = FlociAuditExporter(settings=settings)
    with pytest.raises(PolicyViolationError) as exc_info:
        exporter.export_event(_sample_audit_event())
    assert exc_info.value.category == "floci_disabled"


def test_floci_blocks_real_aws_cloud_endpoints():
    settings = Settings(
        app_profile="local",
        enable_floci=True,
        floci_endpoint_url="https://s3.us-east-1.amazonaws.com",
    )
    exporter = FlociAuditExporter(settings=settings)
    with pytest.raises(PolicyViolationError) as exc_info:
        exporter.export_event(_sample_audit_event())
    assert exc_info.value.category == "non_local_cloud_endpoint_denied"


def test_floci_exports_synthetic_audit_to_localhost_only():
    recorded_urls: list[str] = []
    settings = Settings(
        app_profile="local",
        enable_floci=True,
        floci_endpoint_url="http://localhost:4566",
        floci_bucket="synthetic-audit-events",
    )
    exporter = FlociAuditExporter(
        settings=settings,
        transport=_mock_floci_transport(recorded_urls),
    )
    url = exporter.export_event(_sample_audit_event())

    assert url == "http://localhost:4566/synthetic-audit-events/audit/req-synthetic-001.json"
    assert len(recorded_urls) == 2
    assert all(u.startswith("http://localhost:4566/") for u in recorded_urls)