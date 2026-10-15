from typing import Optional
from urllib.parse import urlparse
import httpx
from app.config import Settings
from app.providers.base import PolicyViolationError, ProviderUnavailableError
from app.schemas import AuditEvent

LOCAL_LOOPBACK_HOSTS = {"localhost", "127.0.0.1"}


def assert_local_emulator_url(endpoint_url: str) -> None:
    """Ensure Floci tests never contact a real cloud endpoint."""
    parsed = urlparse(endpoint_url)
    if parsed.scheme not in {"http", "https"} or parsed.hostname not in LOCAL_LOOPBACK_HOSTS:
        raise PolicyViolationError(
            f"Floci endpoint '{endpoint_url}' denied: only localhost/127.0.0.1 is permitted.",
            category="non_local_cloud_endpoint_denied",
        )


class FlociAuditExporter:
    """Exports metadata-only synthetic audit events to a local Floci S3 emulator."""

    def __init__(
        self,
        settings: Settings,
        transport: Optional[httpx.BaseTransport] = None,
    ):
        self.settings = settings
        self.endpoint_url = settings.floci_endpoint_url.rstrip("/")
        self.bucket = settings.floci_bucket
        self._transport = transport

    def export_event(self, event: AuditEvent) -> str:
        if not self.settings.enable_floci:
            raise PolicyViolationError(
                "Floci export requested while ENABLE_FLOCI is false.",
                category="floci_disabled",
            )
        if self.settings.app_profile == "mock":
            raise PolicyViolationError(
                "Floci integration is not permitted in corporate 'mock' profile.",
                category="floci_profile_denied",
            )

        assert_local_emulator_url(self.endpoint_url)

        object_key = f"audit/{event.request_id}.json"
        bucket_url = f"{self.endpoint_url}/{self.bucket}"
        object_url = f"{bucket_url}/{object_key}"

        # Explicit dummy credentials only; never reads real AWS environment credentials
        dummy_headers = {
            "Authorization": "AWS4-HMAC-SHA256 Credential=test/20260101/us-east-1/s3/aws4_request",
            "Content-Type": "application/json",
            "X-Amz-Content-Sha256": "UNSIGNED-PAYLOAD",
        }

        try:
            with httpx.Client(timeout=10.0, transport=self._transport) as client:
                # Ensure synthetic bucket exists in local emulator
                client.put(bucket_url, headers=dummy_headers)
                # Upload metadata-only audit record
                resp = client.put(
                    object_url,
                    content=event.model_dump_json(),
                    headers=dummy_headers,
                )
        except httpx.RequestError as exc:
            raise ProviderUnavailableError(
                f"Floci emulator unreachable at {self.endpoint_url}: {exc}"
            ) from exc

        if resp.status_code >= 400:
            raise ProviderUnavailableError(
                f"Floci emulator returned HTTP {resp.status_code}: {resp.text[:200]}"
            )

        return object_url