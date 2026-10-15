from datetime import datetime, timezone
from typing import List, Literal, Optional
from pydantic import BaseModel, ConfigDict, Field

DataClass = Literal["synthetic", "internal", "restricted"]
SimMode = Literal[
    "ok",
    "rate_limit_429",
    "auth_error_401",
    "service_error_503",
    "quota_exceeded_402",
]


class LLMRequest(BaseModel):
    """Public request body. Request IDs and provider routes are decided server-side, never by the caller."""

    model_config = ConfigDict(extra="forbid")

    prompt: str = Field(..., min_length=1)
    model: str = Field(default="mock-coder-v1")
    data_classification: DataClass = Field(default="synthetic")
    use_rag: bool = Field(default=False)
    simulate_primary: SimMode = Field(default="ok")
    simulate_fallback: SimMode = Field(default="ok")


class LLMResponse(BaseModel):
    request_id: str
    selected_provider: str
    model: str
    content: str
    fallback_used: bool = False
    fallback_reason: Optional[str] = None
    latency_ms: float
    prompt_tokens: int
    completion_tokens: int
    retrieved_chunks: List[str] = Field(default_factory=list)


class AuditEvent(BaseModel):
    """Metadata-only audit record. Raw prompts and outputs are strictly excluded."""
    request_id: str
    timestamp: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    app_profile: str
    requested_provider: str
    selected_provider: str
    model: str
    status_category: str
    fallback_used: bool
    fallback_reason: Optional[str] = None
    latency_ms: float
    prompt_tokens: int = 0
    completion_tokens: int = 0