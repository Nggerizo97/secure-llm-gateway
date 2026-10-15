# Engineering & Security Review Demo Script

Follows plan §12. Commands are PowerShell; every step uses synthetic prompts and the `sample_project/` code only. Never use live company code.

Run from the repository root with the virtual environment active and `pip install -e ".[dev]"` done.

---

## Part A — Corporate mock profile (offline, steps 1–7)

### 1. Start the mock profile and show the route

```powershell
$env:APP_PROFILE = "mock"
$env:ENABLE_RAG = "false"
$env:ENABLE_FLOCI = "false"
Remove-Item Env:PRIMARY_PROVIDER, Env:FALLBACK_PROVIDER, Env:ALLOW_SIMULATION -ErrorAction SilentlyContinue
python -m pytest -v
```

Point out: every test passes with no model server, no API key, no ChromaDB, no Floci, and no network.

### 2–6. Routing demo

```powershell
python -m app.cli demo --provider mock
```

Walk through the four printed scenarios:

| Demo output | Plan step | What to say |
|---|---|---|
| `[1. Primary Success]` | 2 | Normal request; server-generated request ID; primary served it. |
| `[2. HTTP 429 Fallback]` | 3–4 | Simulated rate limit → configured, allowlisted fallback (`mock_fallback`). `reason=rate_limit`. |
| `[3. Fallback Failure]` | 5 | Fallback also fails (503) → clear error, no third provider is guessed. |
| `[4. Auth 401 No-Fallback]` | 6 | Authentication failure is **not** rerouted. |

### 6b. Show that a caller cannot force or redirect a fallback (HTTP API)

In a second terminal:

```powershell
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Back in the first terminal:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/health
```

Shows the server-side route (`mock` → `mock_fallback`) and `simulation_enabled`.

```powershell
Invoke-WebRequest -Method Post http://127.0.0.1:8000/v1/generate -ContentType "application/json" -Body '{"prompt":"x","fallback_provider":"personal_api"}' -SkipHttpErrorCheck | Select-Object StatusCode, Content
```

Expected: **422** — the body cannot pick providers (or request IDs).

```powershell
Invoke-WebRequest -Method Post http://127.0.0.1:8000/v1/generate -ContentType "application/json" -Body '{"prompt":"x","model":"unapproved-gpt-5"}' -SkipHttpErrorCheck | Select-Object StatusCode, Content
```

Expected: **403** `model_denied`, with the `request_id` that appears in the audit log.

To show simulation lock-down, stop uvicorn, set `$env:ALLOW_SIMULATION = "false"`, restart it, and send `{"prompt":"x","simulate_primary":"rate_limit_429"}` → **403** `simulation_disabled`. (In the `enterprise` profile simulation is always off.) Then `Remove-Item Env:ALLOW_SIMULATION`.

### 7. Audit metadata contains no prompts, outputs, or credentials

```powershell
python -m app.cli audit-report
```

Then show the audit table schema has no prompt/output columns:

```powershell
python -c "import sqlite3; c=sqlite3.connect('data/audit.db'); print([r[1] for r in c.execute('PRAGMA table_info(audit_events)')])"
```

`tests/test_gateway_phase1.py::test_no_prompt_logging` proves a unique marker from the prompt never reaches the database.

---

## Part B — Personal computer only (steps 8–10)

### 8. Same synthetic prompts through local Ollama

Prerequisites: Ollama installed and running, model pulled.

```powershell
ollama pull qwen2.5-coder:7b
```

```powershell
$env:APP_PROFILE = "local"
python -m app.cli demo --provider mock
```

Route is `mock` → `ollama`: scenario 2 now shows the rate-limited primary failing over to the **local model** (real inference, no external API).

```powershell
python -m app.cli demo --provider ollama
```

Ollama is primary here; scenario 1 shows real local inference and its latency. Compare `avg_ollama_latency_ms` vs `avg_fallback_latency_ms` in `python -m app.cli audit-report`.

### 9. Optional — ChromaDB retrieval over the synthetic sample project

```powershell
python -m pip install -e ".[local]"
$env:APP_PROFILE = "local"
$env:ENABLE_RAG = "true"
python -m app.cli rag-demo
```

Shows the retrieved chunks (visible diagnostics) from `sample_project/retry_helper.py`. Note: the demo uses a local hash-based embedding (no network), which is deliberately simple — retrieval quality is not representative of a real embedding model. Vectors persist under `data/chroma/`, which Git ignores.

```powershell
$env:ENABLE_RAG = "false"
```

### 10. Optional — Floci persistence of synthetic audit metadata

```powershell
docker compose --profile floci up -d
$env:APP_PROFILE = "local"
$env:ENABLE_FLOCI = "true"
python -m app.cli floci-demo
```

The object URL must be `http://localhost:4566/...`. Any non-loopback endpoint is refused (`non_local_cloud_endpoint_denied`); dummy credentials only.

```powershell
docker compose --profile floci down
$env:ENABLE_FLOCI = "false"
```

---

## Part C — Close (step 11)

1. Data flow: [architecture.md](architecture.md).
2. Known limitations:
   - No caller authentication on the HTTP API yet (bind to `127.0.0.1`).
   - Data-class approval is per profile, not per provider.
   - Unexpected (non-gateway) exceptions are not yet written to the audit log.
   - Secret detection is a short regex list, not DLP.
   - RAG embeddings are a demo hash function.
3. What approval is needed to connect a company-managed endpoint: [security-review-checklist.md](security-review-checklist.md) and plan §14 go/no-go checklist. Until then the `enterprise` profile fails closed and the app stays in mock mode.
