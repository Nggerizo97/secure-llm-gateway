import os
from typing import Literal, Optional
from pydantic import BaseModel, Field, model_validator

ProfileType = Literal["mock", "local", "enterprise"]

# Server-side (primary, fallback) route per profile. Callers of the HTTP API cannot change it.
DEFAULT_ROUTES: dict[str, tuple[str, Optional[str]]] = {
    "mock": ("mock", "mock_fallback"),
    "local": ("mock", "ollama"),
    "enterprise": ("enterprise", None),
}


class Settings(BaseModel):
    app_profile: ProfileType = Field(default="mock")
    enable_rag: bool = Field(default=False)
    enable_floci: bool = Field(default=False)
    ollama_base_url: str = Field(default="http://localhost:11434")
    ollama_model: str = Field(default="qwen2.5-coder:7b")
    audit_store: Literal["sqlite", "memory"] = Field(default="sqlite")
    audit_db_path: str = Field(default="./data/audit.db")
    floci_endpoint_url: str = Field(default="http://localhost:4566")
    floci_bucket: str = Field(default="synthetic-audit-events")
    # "" -> profile default route; fallback None or "none" -> fallback disabled
    primary_provider: str = Field(default="")
    fallback_provider: Optional[str] = Field(default="")
    # None -> enabled for mock/local, disabled for enterprise
    allow_simulation: Optional[bool] = Field(default=None)

    @model_validator(mode="after")
    def _apply_profile_defaults(self) -> "Settings":
        default_primary, default_fallback = DEFAULT_ROUTES[self.app_profile]
        if not self.primary_provider:
            self.primary_provider = default_primary
        if self.fallback_provider == "":
            self.fallback_provider = default_fallback
        elif self.fallback_provider is not None and self.fallback_provider.lower() == "none":
            self.fallback_provider = None

        if self.allow_simulation is None:
            self.allow_simulation = self.app_profile != "enterprise"
        elif self.allow_simulation and self.app_profile == "enterprise":
            raise ValueError("Fault simulation cannot be enabled in the 'enterprise' profile.")
        return self

    @classmethod
    def from_env(cls) -> "Settings":
        raw_rag = os.getenv("ENABLE_RAG", "false").lower() == "true"
        raw_floci = os.getenv("ENABLE_FLOCI", "false").lower() == "true"
        raw_simulation = os.getenv("ALLOW_SIMULATION")
        return cls(
            app_profile=os.getenv("APP_PROFILE", "mock"),  # type: ignore[arg-type]
            enable_rag=raw_rag,
            enable_floci=raw_floci,
            ollama_base_url=os.getenv("OLLAMA_BASE_URL", "http://localhost:11434"),
            ollama_model=os.getenv("OLLAMA_MODEL", "qwen2.5-coder:7b"),
            audit_store=os.getenv("AUDIT_STORE", "sqlite"),  # type: ignore[arg-type]
            audit_db_path=os.getenv("AUDIT_DB_PATH", "./data/audit.db"),
            floci_endpoint_url=os.getenv("FLOCI_ENDPOINT_URL", "http://localhost:4566"),
            floci_bucket=os.getenv("FLOCI_BUCKET", "synthetic-audit-events"),
            primary_provider=os.getenv("PRIMARY_PROVIDER", ""),
            fallback_provider=os.getenv("FALLBACK_PROVIDER", ""),
            allow_simulation=None if raw_simulation is None else raw_simulation.lower() == "true",
        )
