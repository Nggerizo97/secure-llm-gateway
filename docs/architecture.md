# Architecture Overview

## Profiles
- **`mock` (Default / Corporate):** Offline deterministic provider. Zero external network egress, no Ollama/ChromaDB/Floci required.
- **`local` (Personal Machine):** Enables local Ollama inference (`http://localhost:11434`), optional ChromaDB RAG (`./data/chroma`), and optional Floci local AWS emulation (`http://localhost:4566`).
- **`enterprise` (Requires Approval):** Fails closed until configured with a company-approved model endpoint and identity mechanism.

## Request Lifecycle
0. The gateway generates the `request_id` and takes the (primary, fallback) route from server configuration (`DEFAULT_ROUTES` / `PRIMARY_PROVIDER` / `FALLBACK_PROVIDER`). The request body cannot set either; unknown fields are rejected.
1. `PolicyEngine` validates `app_profile`, `data_classification`, provider/model allowlists, RAG flag, secret patterns, and whether fault simulation is allowed (off in `enterprise`).
2. Optional `ChromaRetrievalStore` augments the prompt with synthetic code chunks when `ENABLE_RAG=true` and `use_rag=true`.
3. `GatewayRouter` invokes the primary provider and only fails over to an allowlisted fallback on retryable capacity errors (`HTTP 429` / `HTTP 503`).
4. `AuditLogger` records metadata-only telemetry (latency, token counts, status category) in SQLite without storing prompts or completions.