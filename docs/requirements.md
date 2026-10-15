# Demo Requirements

## Goal

Show that when the company-provided LLM runs out of tokens, a developer's requests can fail over to an **approved** alternative model, either:

- a **self-hosted model on a separate machine**, reached only over an encrypted private network, or
- an **external LLM API** called with a controlled key,

with policy enforcement, no prompt retention, and a metadata-only audit trail.

## Honesty constraint

The machine that runs the fallback model necessarily processes the prompts. The demo therefore **does not** claim that data "never touches" that machine. Instead:

- Machine B (the second computer) **stands in for a company-controlled model server**. In production it lives in the company's own cloud/VPC.
- The demo proves the **architecture and controls**, not that an unmanaged personal device is trustworthy.
- **Synthetic data only.** The real company laptop is not used until IT/security approve it.

## Roles

| Role | Demo stand-in | Production equivalent |
|---|---|---|
| Machine A — developer workstation + gateway | Personal laptop, VM or WSL | Company laptop / company-hosted gateway |
| Machine B — model server | Second personal machine running Ollama behind a token-checking proxy | Model server in the company VPC |
| Primary provider | Any OpenAI-compatible API (`openai_compat`) | Company-contracted LLM (or Copilot via approved BYOK) |
| Private network | WireGuard / Tailscale tunnel | Company VPN / private connectivity |

## Requirements

Status: ✅ done and tested · 🟡 implemented, not yet run on the target machine (WSL) · ⬜ to do

### Functional

| ID | Requirement | Status | Evidence |
|---|---|---|---|
| R1 | Call a real primary LLM through an OpenAI-compatible API using a configured key and model | ✅ | `app/providers/openai_compat.py`; `test_external_provider_success_sends_key_and_configured_model` |
| R2 | A real upstream HTTP 429 (rate limit) triggers fallback to the configured route | ✅ | `test_real_http_429_falls_back_to_remote_model` |
| R3 | Budget exhaustion (HTTP 402 / 429 `insufficient_quota`) falls back **only** when `FALLBACK_ON_QUOTA_EXHAUSTED=true` (approved alternative budget) | ✅ | `test_quota_exhausted_*` |
| R4 | Fallback can target a self-hosted model on another machine | ✅ | Run on WSL (2026-10-15): mock company provider hit its budget, returned 429, and requests 5–6 were answered by `qwen2.5-coder:1.5b` on WSL over verified TLS + token |
| R5 | Auth errors, other 4xx (e.g. content policy) and malformed responses never reroute | ✅ | `test_non_capacity_errors_never_reroute` |
| R6 | Routes and request IDs are server-controlled; callers cannot choose providers | ✅ | `tests/test_request_integrity.py` |
| R7 | Developer tools can use the gateway via an OpenAI-compatible `/v1/chat/completions` endpoint | ⬜ | — |
| R8 | A stand-in company provider returns a real HTTP 429 when its token budget runs out (no paid key needed) | ✅ | `mock_provider/service.py`; `tests/test_mock_company_provider.py` |
| R9 | Operators can send real prompts along the configured route and watch the failover | ✅ | `python -m app.cli ask "..." --repeat N` |

### Security

| ID | Requirement | Status | Evidence |
|---|---|---|---|
| S1 | Self-hosted model endpoints must resolve to loopback, private or tunnel (100.64.0.0/10) addresses; public, unspecified and link-local addresses are denied, including via DNS | ✅ | `app/network_policy.py`; `test_remote_ollama_*` |
| S2 | Remote model calls require a bearer token, and HTTPS unless the operator confirms an encrypted tunnel (`OLLAMA_ALLOW_PLAINTEXT_TUNNEL`) | ✅ | Client side tested; server-side enforcement is S7 |
| S3 | External API endpoints must use HTTPS (plain HTTP only for loopback) | ✅ | `test_external_provider_fails_closed_when_misconfigured` |
| S4 | Keys come from environment / secret store, are held as `SecretStr`, and never appear in logs, audit or error messages; upstream error bodies are not echoed | ✅ | `test_api_keys_never_appear_*`, `test_upstream_error_body_is_not_echoed` |
| S5 | Audit log is metadata-only and insert-only | ✅ | `test_no_prompt_logging`, `test_request_ids_are_server_generated_and_audit_is_insert_only` |
| S6 | Callers must authenticate to the gateway API | ⬜ | — |
| S7 | Machine B: reverse proxy enforces the token and TLS and exposes only `POST /api/generate` over TCP; Ollama binds only to localhost behind it; no debug/prompt logging; the token is never written to Caddy's config autosave | ✅ | `verify.sh` 9/9 PASS on WSL (2026-10-15); `deploy/model-server/Caddyfile`, `setup.sh`, `start-proxy.sh` |
| S8 | Machine B firewall accepts model traffic only from machine A; optional lockdown blocks all outbound connections | ✅ | `firewall.sh secure` on WSL (2026-10-15): a listener on a non-allowed port (9999) was unreachable from Windows while 8443 stayed reachable and failover kept working. `firewall.sh lockdown`: WSL could not reach example.com, ollama.com or 1.1.1.1, DNS failed, and failover to the WSL model still worked |

### Evidence for reviewers

| ID | Requirement | Status |
|---|---|---|
| E1 | Step-by-step two-machine demo guide | ✅ [two-machine-demo.md](two-machine-demo.md) |
| E2 | Packet capture showing a canary from the prompt is absent from traffic to machine B (TLS) | ✅ `evidence.sh` on WSL (2026-10-15): 34 packets captured, canary absent |
| E3 | Canary search of every file changed on machine B and its system journal shows no prompts persisted | ✅ `evidence.sh` on WSL (2026-10-15): the model received the canary (it quoted it in its reply), yet it was absent from all 6 changed files and the journal |
| E4 | All tests run offline (no network, model server or real key) | ✅ |
| E5 | Synthetic sample code only | ✅ |

## Configuration for the target demo

```text
APP_PROFILE=local
PRIMARY_PROVIDER=openai_compat
FALLBACK_PROVIDER=ollama

OPENAI_COMPAT_BASE_URL=https://<provider>/v1
OPENAI_COMPAT_MODEL=<model>
OPENAI_COMPAT_API_KEY=<from secret store; never committed>

OLLAMA_BASE_URL=https://<machine-B tunnel address>:11434
OLLAMA_API_KEY=<proxy token; never committed>
# OLLAMA_CA_BUNDLE=<path to the proxy's CA certificate, if self-signed>
# OLLAMA_ALLOW_PLAINTEXT_TUNNEL=true   # only for a WireGuard/Tailscale address without TLS
```

## Next steps

1. **R7, S6:** OpenAI-compatible endpoint with caller authentication, so real developer tools can use the gateway.
