from typing import Any, Dict, List
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from app.audit import AuditLogger
from app.config import Settings
from app.policy import ALLOWED_MODELS_BY_PROFILE, ALLOWED_PROVIDERS_BY_PROFILE, PolicyEngine
from app.providers.base import GatewayError
from app.providers.enterprise import EnterpriseProvider
from app.providers.mock import MockProvider
from app.providers.ollama import OllamaProvider
from app.router import GatewayRouter
from app.schemas import AuditEvent, LLMRequest, LLMResponse


def build_router(settings: Settings | None = None) -> GatewayRouter:
    cfg = settings or Settings.from_env()
    audit_path = ":memory:" if cfg.audit_store == "memory" else cfg.audit_db_path
    audit = AuditLogger(db_path=audit_path)
    policy = PolicyEngine(settings=cfg)

    retrieval_store = None
    if cfg.enable_rag:
        from app.retrieval.chroma_store import ChromaRetrievalStore

        retrieval_store = ChromaRetrievalStore(persist_dir="./data/chroma")
        retrieval_store.index_directory("./sample_project")

    providers = {
        "mock": MockProvider(name="mock"),
        "mock_fallback": MockProvider(name="mock_fallback"),
        "ollama": OllamaProvider(
            base_url=cfg.ollama_base_url,
            default_model=cfg.ollama_model,
        ),
        "enterprise": EnterpriseProvider(),
    }
    return GatewayRouter(
        settings=cfg,
        policy=policy,
        audit=audit,
        providers=providers,
        retrieval_store=retrieval_store,
    )


def create_app(settings: Settings | None = None) -> FastAPI:
    app = FastAPI(
        title="Secure LLM Gateway",
        version="0.2.0",
        description="Policy-controlled LLM routing gateway with deterministic fallback",
    )
    router = build_router(settings)
    app.state.gateway_router = router

    @app.exception_handler(GatewayError)
    async def gateway_error_handler(request, exc: GatewayError):
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error": str(exc),
                "category": exc.category,
                "retryable": exc.retryable,
                "request_id": exc.request_id,
            },
        )

    @app.get("/health")
    def health() -> dict:
        cfg = app.state.gateway_router.settings
        return {
            "status": "ok",
            "app_profile": cfg.app_profile,
            "enable_rag": cfg.enable_rag,
            "route": {"primary": cfg.primary_provider, "fallback": cfg.fallback_provider},
            "simulation_enabled": cfg.allow_simulation,
            "allowed_providers": sorted(
                ALLOWED_PROVIDERS_BY_PROFILE.get(cfg.app_profile, set())
            ),
            "allowed_models": sorted(
                ALLOWED_MODELS_BY_PROFILE.get(cfg.app_profile, set())
            ),
        }

    @app.post("/v1/generate", response_model=LLMResponse)
    def generate(payload: LLMRequest) -> LLMResponse:
        return app.state.gateway_router.route(payload)

    @app.get("/v1/audit", response_model=List[AuditEvent])
    def get_audit_events(limit: int = 20) -> List[AuditEvent]:
        return app.state.gateway_router.audit.list_events(limit=limit)

    @app.get("/v1/metrics")
    def get_metrics() -> Dict[str, Any]:
        return app.state.gateway_router.audit.compute_metrics()

    return app


app = create_app()