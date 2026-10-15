# Security Review & Boundary Checklist (Phase 0)

## 1. Scope & Environment Boundaries
- **Corporate Environment (`APP_PROFILE=mock`):** Uses synthetic code and deterministic in-memory mock responses only. Zero network egress, no external API keys, and no unapproved binaries (Ollama, ChromaDB, Docker/Floci).
- **Personal Environment (`APP_PROFILE=local`):** May enable local Ollama inference and local ChromaDB persistence over synthetic sample code only. Never ingests corporate code or credentials.
- **Enterprise Profile (`APP_PROFILE=enterprise`):** Disabled (fails closed) until written security/AI platform approval is granted.

## 2. Verification Gates
- [x] Default profile is `mock` and rejects unknown profiles.
- [x] Fallback triggers ONLY on retryable capacity errors (HTTP 429 / 503).
- [x] Auth (401/403) and policy errors never trigger provider fallback.
- [x] Audit SQLite database stores metadata only (zero prompts or model completions).
- [ ] Written approval obtained before configuring real corporate model endpoints.