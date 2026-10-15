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

Status: ✅ done and tested · 🟡 partly done · ⬜ to do

### Functional

| ID | Requirement | Status | Evidence |
|---|---|---|---|
| R1 | Call a real primary LLM through an OpenAI-compatible API using a configured key and model | ✅ | `app/providers/openai_compat.py`; `test_external_provider_success_sends_key_and_configured_model` |
| R2 | A real upstream HTTP 429 (rate limit) triggers fallback to the configured route | ✅ | `test_real_http_429_falls_back_to_remote_model` |
| R3 | Budget exhaustion (HTTP 402 / 429 `insufficient_quota`) falls back **only** when `FALLBACK_ON_QUOTA_EXHAUSTED=true` (approved alternative budget) | ✅ | `test_quota_exhausted_*` |
| R4 | Fallback can target a self-hosted model on another machine | 🟡 | Gateway side done (`OllamaProvider` remote mode); machine B setup is S7–S8 |
| R5 | Auth errors, other 4xx (e.g. content policy) and malformed responses never reroute | ✅ | `test_non_capacity_errors_never_reroute` |
| R6 | Routes and request IDs are server-controlled; callers cannot choose providers | ✅ | `tests/test_request_integrity.py` |
| R7 | Developer tools can use the gateway via an OpenAI-compatible `/v1/chat/completions` endpoint | ⬜ | — |

### Security

| ID | Requirement | Status | Evidence |
|---|---|---|---|
| S1 | Self-hosted model endpoints must resolve to loopback, private or tunnel (100.64.0.0/10) addresses; public, unspecified and link-local addresses are denied, including via DNS | ✅ | `app/network_policy.py`; `test_remote_ollama_*` |
| S2 | Remote model calls require a bearer token, and HTTPS unless the operator confirms an encrypted tunnel (`OLLAMA_ALLOW_PLAINTEXT_TUNNEL`) | 🟡 | Client side tested; the proxy on machine B that **checks** the token is S7 |
| S3 | External API endpoints must use HTTPS (plain HTTP only for loopback) | ✅ | `test_external_provider_fails_closed_when_misconfigured` |
| S4 | Keys come from environment / secret store, are held as `SecretStr`, and never appear in logs, audit or error messages; upstream error bodies are not echoed | ✅ | `test_api_keys_never_appear_*`, `test_upstream_error_body_is_not_echoed` |
| S5 | Audit log is metadata-only and insert-only | ✅ | `test_no_prompt_logging`, `test_request_ids_are_server_generated_and_audit_is_insert_only` |
| S6 | Callers must authenticate to the gateway API | ⬜ | — |
| S7 | Machine B: reverse proxy enforces the token and TLS; Ollama binds only to localhost behind it; no debug/prompt logging | ⬜ | — |
| S8 | Machine B firewall accepts model traffic only from machine A over the tunnel | ⬜ | — |

### Evidence for reviewers

| ID | Requirement | Status |
|---|---|---|
| E1 | Step-by-step two-machine demo guide | ⬜ |
| E2 | Packet capture showing only encrypted traffic between A and B's tunnel address | ⬜ |
| E3 | Before/after file snapshot of machine B showing no prompts persisted | ⬜ |
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

1. **S7, S8, E1:** machine B setup (proxy config, firewall, Ollama settings) and the two-machine guide.
2. **R7, S6:** OpenAI-compatible endpoint with caller authentication, so real developer tools can use the gateway.
3. **E2, E3:** evidence kit (capture and snapshot scripts).
