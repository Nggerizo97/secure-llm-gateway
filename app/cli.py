import argparse
import json
from app.main import build_router
from app.providers.base import GatewayError
from app.schemas import LLMRequest
from app.floci_exporter import FlociAuditExporter


def run_demo(provider: str) -> None:
    router = build_router()
    settings = router.settings
    fallback_target = (
        "ollama"
        if (settings.app_profile == "local" and provider == "mock")
        else "mock_fallback"
    )
    # Operator-side route override; still checked against the profile allowlist.
    route = {"primary_provider": provider, "fallback_provider": fallback_target}

    print(
        f"=== Secure LLM Gateway Demo (Profile: {settings.app_profile} | Primary: {provider} | Fallback: {fallback_target}) ==="
    )

    # 1. Normal primary success
    req1 = LLMRequest(
        prompt="Write a one-line Python function that adds two numbers.",
    )
    res1 = router.route(req1, **route)
    print(
        f"\n[1. Primary Success] req_id={res1.request_id} | provider={res1.selected_provider} "
        f"| model={res1.model} | latency={res1.latency_ms}ms | fallback={res1.fallback_used}"
    )
    print(f"    Output: {res1.content[:120]}")

    # 2. Simulated HTTP 429 -> Allowed Fallback
    req2 = LLMRequest(
        prompt="Write a one-line Python lambda for squaring an integer.",
        simulate_primary="rate_limit_429",
    )
    res2 = router.route(req2, **route)
    print(
        f"\n[2. HTTP 429 Fallback] req_id={res2.request_id} | provider={res2.selected_provider} "
        f"| reason={res2.fallback_reason} | latency={res2.latency_ms}ms"
    )
    print(f"    Output: {res2.content[:120]}")

    # 3. Simulated Fallback Failure
    req3 = LLMRequest(
        prompt="Generate unit test stub.",
        simulate_primary="rate_limit_429",
        simulate_fallback="service_error_503",
    )
    try:
        router.route(req3, **route)
    except GatewayError as err:
        print(
            f"\n[3. Fallback Failure] req_id={err.request_id} | status={err.status_code} | category={err.category}"
        )

    # 4. Simulated HTTP 401 Auth Error -> Must NOT Fallback
    req4 = LLMRequest(
        prompt="Check auth boundary behavior.",
        simulate_primary="auth_error_401",
    )
    try:
        router.route(req4, **route)
    except GatewayError as err:
        print(
            f"\n[4. Auth 401 No-Fallback] req_id={err.request_id} | status={err.status_code} | category={err.category} (Fallback blocked)"
        )

    # 5. Audit Metadata Verification
    print("\n=== Recent Audit Metadata (Prompts/Outputs Excluded) ===")
    for ev in router.audit.list_events(limit=4):
        print(
            f" - id={ev.request_id[:8]}... | req_prov={ev.requested_provider} -> sel_prov={ev.selected_provider} "
            f"| status={ev.status_category} | fallback={ev.fallback_used} | tokens={ev.prompt_tokens}/{ev.completion_tokens}"
        )


def run_audit_report() -> None:
    router = build_router()
    metrics = router.audit.compute_metrics()
    print("=== Gateway Audit & Success Metrics Report ===")
    print(json.dumps(metrics, indent=2))


def run_rag_demo(provider: str) -> None:
    router = build_router()
    req = LLMRequest(
        prompt="How does compute_backoff_seconds calculate retry delay in retry_helper.py?",
        use_rag=True,
    )
    res = router.route(req, primary_provider=provider)
    print(f"=== RAG Demo (Provider: {res.selected_provider} | Chunks Retrieved: {len(res.retrieved_chunks)}) ===")
    for idx, chunk in enumerate(res.retrieved_chunks, 1):
        print(f"  Chunk {idx}: {chunk}")
    print(f"\nResponse:\n{res.content}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Secure LLM Gateway CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    demo_parser = subparsers.add_parser("demo", help="Run reproducible routing demo")
    demo_parser.add_argument("--provider", default="mock", help="Primary provider name (mock or ollama)")

    subparsers.add_parser("audit-report", help="Print Section 13 audit metrics summary")

    rag_parser = subparsers.add_parser("rag-demo", help="Run optional ChromaDB retrieval demo")
    rag_parser.add_argument("--provider", default="mock", help="Primary provider name (mock or ollama)")

    subparsers.add_parser("floci-demo", help="Export latest synthetic audit event to local Floci emulator")

    args = parser.parse_args()
    if args.command == "demo":
        run_demo(args.provider)
    elif args.command == "audit-report":
        run_audit_report()
    elif args.command == "rag-demo":
        run_rag_demo(args.provider)
    elif args.command == "floci-demo":
        run_floci_demo()

def run_floci_demo() -> None:
    router = build_router()
    res = router.route(
        LLMRequest(prompt="Synthetic request for Floci audit persistence demo."),
        primary_provider="mock",
    )
    latest_event = router.audit.list_events(limit=1)[0]
    exporter = FlociAuditExporter(settings=router.settings)
    object_url = exporter.export_event(latest_event)
    print("=== Floci Audit Export Demo ===")
    print(f"Request ID : {res.request_id}")
    print(f"Local URL  : {object_url}")
    print(f"Payload    : {latest_event.model_dump_json()}")

if __name__ == "__main__":
    main()
