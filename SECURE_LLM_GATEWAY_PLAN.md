# Secure LLM Gateway — Cross-Computer Demo and Enterprise Plan

**Status:** Proposal / implementation blueprint  
**Primary goal:** Demonstrate safe, policy-controlled LLM fallback when an approved model endpoint reaches a rate limit, without depending on unapproved software on the corporate computer.  
**Development strategy:** One Git repository, with a portable mock-only mode for the corporate computer and optional local-model/RAG/cloud-emulator profiles on a personal computer.

> **Security boundary:** This project must not be used to bypass corporate AI policy, Copilot controls, endpoint management, network restrictions, or provider quotas. The corporate deployment and any access to real company code or internal model endpoints require approval from the appropriate team. Develop with synthetic code and mock data until that approval exists.

---

## 1. Executive summary

Build a small Python service that provides a consistent interface for LLM requests, applies routing policy, records minimal audit metadata, and can demonstrate failover from a simulated primary-model rate limit to an allowed fallback.

The repository must work in two different environments:

1. **Personal computer — full local demo:** run a local LLM using Ollama; optionally enable ChromaDB retrieval and Floci for local AWS-integration tests.
2. **Corporate computer — constrained demo/development:** edit the same repository with the existing approved tools and GitHub Copilot. The default `mock` profile must not require Ollama, ChromaDB, Floci, a personal API key, or any external LLM calls. If the company does not allow a local Python runtime or project dependencies, use the approved development environment/CI and do not attempt to bypass endpoint controls.

The same codebase supports both environments through configuration and optional adapters. Local-only features must not be required for the core tests to pass.

### Important Copilot distinction

Use the company-provided GitHub Copilot license to help **write and maintain this repository** in the approved IDE. Do not assume that a Copilot license is a general-purpose API key that this gateway can call, or that Copilot's quota can be transparently used by a separate service.

VS Code documents a Bring Your Own Key (BYOK) capability for compatible external or local model endpoints. For Copilot Business/Enterprise, an administrator can restrict this capability. If the company explicitly enables BYOK and approves the gateway endpoint, VS Code may be able to use the approved custom endpoint for supported chat/agent scenarios. BYOK usage follows the chosen provider's rate limits and billing rather than automatically consuming Copilot premium-request quota. Verify current organizational settings and client support before relying on it.

References:
- [GitHub Copilot model access and custom models](https://docs.github.com/en/copilot/how-tos/copilot-on-github/set-up-copilot/configure-access-to-ai-models)
- [VS Code language models, BYOK, and custom endpoints](https://code.visualstudio.com/docs/copilot/customization/language-models)
- [Copilot SDK BYOK and provider limitations](https://docs.github.com/en/copilot/how-tos/copilot-sdk/auth/byok)

---

## 2. Goals and non-goals

### Goals

- Demonstrate provider-independent request routing through a single internal interface.
- Reproduce primary-provider rate limits deterministically, without spending real tokens.
- Route only to a configured, approved fallback.
- Run the core application and tests without external model access.
- Offer optional local inference on the personal computer.
- Add optional code retrieval with ChromaDB, while keeping retrieval disabled by default.
- Add optional Floci-based AWS integration tests if AWS service emulation is useful.
- Share source code through Git without committing secrets, model files, prompts, company code, or local databases.
- Produce evidence that an engineering/security reviewer can reproduce.

### Non-goals for the first prototype

- Circumventing Copilot controls or extracting/repurposing Copilot credentials.
- Sending corporate source code to a personal computer or a personal model/API account.
- Automatically falling back to a personal API key from a corporate request.
- Building a complete coding IDE or replacing GitHub Copilot.
- Production deployment, enterprise SSO, or policy certification before the security team has reviewed the design.
- Treating VPN/VPC placement, redaction, embeddings, or a local database as proof of security by themselves.

---

## 3. Recommended architecture

### Logical view

```text
                         Same Git repository
               +----------------------------------+
               | Source code / tests / docs only  |
               +----------------------------------+
                        /                 \
                       /                   \
         Personal computer             Corporate computer
         FULL LOCAL PROFILE             MOCK / APPROVED PROFILE
         ------------------             -----------------------
         Demo UI / CLI                  VS Code + company Copilot
              |                              |
         FastAPI gateway                FastAPI gateway (if runtime approved)
              |                              |
         Policy + Router                Policy + Router
          /         \                    /         \
   Mock provider  Ollama             Mock provider  Approved endpoint
        |             |                   |          (only after approval)
        +------ optional RAG -------------+
                       |
                 ChromaDB (optional)

   Optional on personal machine/test CI only:
   Floci emulator -> synthetic S3 / DynamoDB audit-integration tests
```

### Request flow

1. A client submits a request to the gateway.
2. The policy layer authenticates the caller where authentication is configured, validates the request, checks the model allowlist, and determines whether local retrieval is allowed.
3. The router sends the request to the configured primary provider.
4. Only recognized, retryable capacity errors—such as a temporary HTTP 429 rate limit—may trigger a fallback, and only if the destination is explicitly approved for that data class.
5. Authentication, authorization, content-policy, or data-classification failures must not be silently converted into a different-provider request.
6. The service returns the response and records metadata such as request ID, selected provider, latency, status category, fallback reason, and token counts when the provider supplies them.
7. Raw prompts and outputs are not stored by default.

### Provider roles

- `mock`: deterministic provider used by default; no network egress and no real LLM token cost.
- `ollama`: optional personal-computer local inference adapter, enabled only through an explicit profile.
- `enterprise`: placeholder/adapter for a company-managed, approved endpoint. Do not configure it with real endpoint details until the company approves the route, identity method, data classification, retention terms, and network path.
- `personal_api`: **not enabled in corporate mode**. It may be used in a separate personal experiment with synthetic data only. Do not allow corporate prompts to route to it.

---

## 4. Technology choices

| Area | Recommendation | Reason |
|---|---|---|
| Main language | Python 3.11+ (pin the exact version in project documentation) | Strong LLM ecosystem, straightforward tests, simple local model and ChromaDB integration. |
| API | FastAPI + Pydantic | Typed request/response contracts and a small API surface. |
| HTTP client | HTTPX | Consistent async HTTP calls and testable provider adapters. |
| Routing | Start with a small provider/router abstraction. Evaluate LiteLLM Proxy as an optional routing engine rather than making the whole design depend on it. | Keeps the core mock mode portable; LiteLLM offers multi-provider routing, retries, cooldowns, and fallbacks when approved. |
| Local inference | Ollama, personal computer only by default | Enables a genuinely local inference path without an external model API. |
| Optional retrieval | ChromaDB with persistent storage under an ignored local data directory | Demonstrates repository-aware Q&A over synthetic sample code. |
| Audit metadata | SQLite for the prototype | Simple local metadata store; do not persist prompts by default. |
| AWS integration testing | Floci, optional | Local AWS-compatible emulator for synthetic S3/DynamoDB integration tests. |
| Tests | pytest; provider fakes/mocks | Reproduce success, rate limit, fallback, deny, and failure cases without real tokens. |
| Code quality | Ruff; type checking if approved by the project's environment | Fast, repeatable static checks. |
| UI | Minimal CLI first; optional Streamlit demo later | Avoid spending time on a front-end before routing/security is proven. |
| Packaging | `pyproject.toml`, lock file, `.env.example`, optional Docker Compose | Reproducible setup with optional services isolated by profile. |

**Keep the core small.** Do not introduce LangChain, an agent framework, Kubernetes, a cloud subscription, or a vector database until a concrete use case requires it. The first proof is fallback behavior and policy enforcement, not agent orchestration.

---

## 5. Cross-computer behavior

### Profile A — `mock` (default; suitable for the constrained company environment)

Requirements:
- Only the already-approved runtime and packages, if local execution is allowed.
- No Ollama, Docker, Floci, ChromaDB, or API credentials.
- No external network connection is required for tests.
- Synthetic sample source code only.

Required commands once the project has been implemented and the environment is approved:

```bash
python -m pytest
python -m app.cli demo --provider mock
```

The exact CLI command can change during implementation, but the default must always be the non-networked mock provider.

### Profile B — `local` (personal computer)

Additional components:
- Ollama installed on the personal computer.
- A locally downloaded coding model supported by the hardware.
- Optional ChromaDB persistence.
- Optional Docker/Floci for AWS integration tests.

Example setup once implementation exists:

```bash
# Create and activate a virtual environment first.
python -m pip install -e ".[dev,local]"
ollama pull qwen2.5-coder:7b
python -m app.cli demo --provider ollama
```

The `local` extra is optional and must not be imported by the core mock path. Model selection is configurable; the example model is a starting point, not a guarantee of performance on every device.

### Profile C — `enterprise` (only after approval)

- Use a company-approved model endpoint, managed identity or approved secret store, and controlled network route.
- Keep keys and endpoints out of Git.
- Require explicit environment configuration and an explicit `enterprise` profile; never silently switch to this profile.
- The security/AI platform team must approve the provider, retention settings, data classes, model fallback, allowed request logging, budgets, and user authentication.
- If the company only authorizes Copilot inside VS Code and does not approve a custom endpoint, use Copilot to work on the repository but keep the application in mock mode. Do not reverse engineer or call Copilot internals as a substitute API.

### Suggested environment variables

Use safe defaults; reject unknown profile values.

```text
APP_PROFILE=mock
ENABLE_RAG=false
ENABLE_FLOCI=false
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=qwen2.5-coder:7b
AUDIT_STORE=sqlite
AUDIT_DB_PATH=./data/audit.db
```

Provider keys, company endpoints, and authentication values must be supplied only through an approved local secret mechanism or managed secret service. Never place real secrets in `.env.example` or in code.

---

## 6. Proposed repository layout

```text
secure-llm-gateway/
├── app/
│   ├── main.py                  # Optional HTTP API entry point
│   ├── cli.py                   # Reproducible demo commands
│   ├── config.py                # Validated settings and safe defaults
│   ├── schemas.py               # Pydantic request/response types
│   ├── policy.py                # Provider/model allowlist and data policy
│   ├── router.py                # Retryable-error and fallback decisions
│   ├── audit.py                 # Metadata-only events; no prompt logging by default
│   ├── providers/
│   │   ├── base.py              # Provider protocol/interface
│   │   ├── mock.py              # Deterministic test provider
│   │   ├── ollama.py            # Optional local provider
│   │   └── enterprise.py        # Approved endpoint adapter; no baked-in secrets
│   └── retrieval/
│       ├── interface.py         # Retrieval protocol
│       └── chroma_store.py      # Optional ChromaDB adapter
├── mock_provider/
│   └── service.py               # Optional mock HTTP provider if needed
├── tests/
│   ├── test_primary_success.py
│   ├── test_rate_limit_fallback.py
│   ├── test_no_fallback_on_auth_error.py
│   ├── test_policy_denies_provider.py
│   ├── test_no_prompt_logging.py
│   └── test_rag_is_optional.py
├── sample_project/              # Synthetic code and documentation only
├── docs/
│   ├── architecture.md
│   ├── threat-model.md
│   ├── security-review-checklist.md
│   └── demo-script.md
├── data/
│   └── .gitkeep                 # Real data and local stores ignored by Git
├── .github/
│   └── workflows/               # CI using mock-only tests, if repo policy allows
├── .gitignore
├── .env.example
├── pyproject.toml
├── compose.yaml                 # Optional profiles only; core mock mode need not use Docker
├── README.md
└── SECURE_LLM_GATEWAY_PLAN.md
```

The `enterprise.py` adapter should fail closed when not explicitly configured. Do not include a real enterprise endpoint in the public repository.

---

## 7. Git strategy for personal and corporate computers

### Repository rules

- Keep the shared repository generic and use synthetic examples.
- First confirm company policy permits creating, cloning, and sharing this repository and whether it must live in a company-controlled Git organization.
- Do not copy corporate application source code, incident data, internal endpoint URLs, keys, model prompts, screenshots, or logs to your personal computer.
- Do not commit `.env` files, API keys, model files/caches, ChromaDB files, SQLite databases, prompt dumps, or company-specific configuration.
- Make profile selection explicit in environment variables; never commit personal endpoint details.
- Keep dependencies pinned and document their purpose. Install packages only in environments where they are approved.
- Use feature branches and small commits. Run mock-only tests before merging.
- If this becomes a company-owned project, migrate the repository to the approved company organization and follow IP, branch protection, and code-review rules.

### `.gitignore` baseline

```gitignore
# Python
.venv/
__pycache__/
*.py[cod]
.pytest_cache/
.ruff_cache/
.mypy_cache/

# Secrets and local configuration
.env
.env.*
!.env.example
*.pem
*.key
secrets/

# Local state, vectors, logs, and model assets
data/**
!data/.gitkeep
.chroma/
chroma/
*.sqlite
*.db
models/
model-cache/
logs/
*.log

# Editor / OS
.vscode/
.idea/
.DS_Store
Thumbs.db
```

Review `.gitignore` with the company team before adding shared VS Code settings; some organizations deliberately version approved workspace configuration.

---

## 8. ChromaDB: add only when needed

ChromaDB is **not required** for request routing or rate-limit fallback. It is useful if the demo needs to retrieve relevant functions or documentation from a synthetic repository.

### RAG flow

1. Index only files in the approved sample folder.
2. Apply file-type allowlists and size limits.
3. Exclude `.env`, private keys, credential files, production dumps, binaries, build artifacts, and `.git` history.
4. Split text into chunks and create embeddings. For a local-only demonstration, use an embedding model/runtime that does not call an external API.
5. Persist ChromaDB under `data/chroma/`, which is ignored by Git.
6. Retrieve only the top few relevant chunks and make that context visible in demo diagnostics.
7. Keep `ENABLE_RAG=false` as the default and test that core routing works without the ChromaDB package installed.

Embeddings and retrieved chunks can reveal information from the original code. Local storage does not remove the need for data classification and access controls.

Reference: [ChromaDB persistent client](https://docs.trychroma.com/docs/run-chroma/cloud-client).

---

## 9. Floci: optional AWS integration tests

Floci is a local AWS service emulator; it is not an LLM runtime or router. Add it only if the prototype needs to validate a planned AWS integration such as saving synthetic audit events to S3 or DynamoDB.

Rules:
- Run Floci only on the personal computer or in approved test CI at first.
- Use synthetic events and dummy credentials.
- Point SDK/CLI endpoints explicitly to the local emulator.
- Never allow an AWS client to silently fall back to a real AWS account during tests.
- Keep Floci storage under ignored local data directories.
- Do not create real cloud resources or use company cloud credentials for the demo.

Reference: [Floci official repository and Compose example](https://github.com/floci-io/floci).

If AWS integration is not part of the review, postpone Floci; it adds complexity without improving the central LLM fallback proof.

---

## 10. Security controls and threat model

| Risk | Prototype control | Production requirement |
|---|---|---|
| Prompt/code accidentally goes to an unapproved provider | Default mock provider; explicit provider allowlist; no automatic personal-key route | Corporate identity, data classification, egress control, provider approval and monitoring |
| Secret appears in a request | Synthetic data in demo; secret-pattern test and deny/redact policy | Approved DLP/secrets detection plus clear policy for false positives |
| API credential leaks into Git/logs | Environment/managed secrets; no prompt logging; secret scanning | Managed secret store, rotation, least privilege, centralized secret scanning |
| Rate limit triggers unsafe fallback | Fallback allowlist and error classification | Approved data-class/model routing, provider contracts and budget controls |
| Authentication/policy error causes alternate-provider bypass | No fallback for 401/403 or content-policy/data-policy errors | Automated policy tests and security monitoring |
| Prompt injection in retrieved files | RAG off by default; treat retrieved content as untrusted data | Isolation and tool permission boundaries; prompt injection testing |
| Logs retain source code | Metadata-only logging | Defined retention, access control, encryption, audit review |
| Local database or embedding store leaks | Data folder ignored by Git; synthetic content only | Encryption/access controls and deletion/retention lifecycle as appropriate |
| Floci test writes to real cloud | Local endpoint is explicit; dummy credentials; tests assert local URL | CI isolation and network/credential boundaries |
| Corporate computer cannot install dependencies | Mock-only mode and approved CI plan | Company-managed deployment or approved developer environment |

### Failure-handling rule

Fallback is a policy decision, not a blanket retry. A transient capacity error may permit fallback; a billing/quota exhaustion may require an approved alternative budget; authentication, authorization, policy violations, and unknown errors must not silently route elsewhere. Limit retries to avoid loops, duplicated costs, and request storms.

---

## 11. Phased delivery plan and acceptance criteria

### Phase 0 — Confirm boundaries

- Confirm the project/repository may be shared across personal and company environments.
- Identify which runtimes and package installations are permitted on the corporate computer.
- Confirm whether Copilot BYOK/custom model endpoints are disabled or enabled by the organization.
- Use synthetic sample source only.

**Done when:** the scope and allowed environments are written in `docs/security-review-checklist.md`.

### Phase 1 — Mock-only core

- Define request and response schemas.
- Implement the provider interface and deterministic mock provider.
- Implement a router that can simulate primary success, rate limit, fallback success, and fallback failure.
- Add structured metadata audit events without prompts or outputs.
- Add unit tests that need no network or local model.

**Acceptance criteria:** all tests pass with no model server, no API key, no ChromaDB, no Floci, and no external egress.

### Phase 2 — Personal local-model profile

- Add the Ollama adapter behind a lazy optional dependency.
- Test local inference with synthetic code.
- Measure latency, success rate, and output usefulness against mock behavior.
- Prove a local-mode request does not require an external LLM API.

**Acceptance criteria:** local inference works on the personal machine; mock tests still pass when Ollama is not installed.

### Phase 3 — Policy and audit hardening

- Add provider/model allowlists and explicit profiles.
- Distinguish temporary rate limits, provider outages, authentication failures, policy failures, and budget exhaustion.
- Add tests proving unauthorized routes are denied.
- Add a metadata audit viewer or CLI report.

**Acceptance criteria:** no fallback can occur to a provider that is not configured and allowed for the request.

### Phase 4 — Optional ChromaDB retrieval

- Add a small indexer for synthetic sample files only.
- Add local embeddings and retrieval.
- Make RAG independently switchable.

**Acceptance criteria:** retrieval-disabled mode works without ChromaDB; the vector store is never committed.

### Phase 5 — Optional Floci integration

- Start a local Floci service only in the AWS-integration profile.
- Save synthetic audit events to local S3/DynamoDB if needed.
- Assert tests are using the local endpoint.

**Acceptance criteria:** no real cloud account is contacted during the test.

### Phase 6 — Company review and approved endpoint

- Present results from the mock-only and personal local profiles.
- Ask the AI platform/security team whether an approved secondary company endpoint or company-hosted model can be configured.
- Only then implement and test the enterprise adapter in a company-managed environment.
- If VS Code BYOK is enabled by policy, validate the exact supported client and endpoint integration. Do not assume all Copilot features, agent sessions, completions, or quotas behave identically.

**Acceptance criteria:** the company team approves the endpoint, data classes, credentials, retention rules, logging, network path, budget limits, and fallback behavior in writing.

---

## 12. Demonstration script

Use this sequence in a short engineering review:

1. Start the mock-only profile and show the selected provider and request ID.
2. Send a normal test request; show primary success.
3. Toggle the mock primary into a simulated HTTP 429 response; send another request.
4. Show fallback to the explicitly configured local/approved provider.
5. Simulate fallback failure; show a safe, clear error with no provider guessing.
6. Simulate an authorization error; demonstrate that the router does **not** switch to another provider.
7. Show audit metadata and verify that prompts, generated source, and credentials are not recorded.
8. On the personal computer only, enable the Ollama profile and run the same synthetic prompt locally.
9. Optionally show ChromaDB retrieval over the synthetic sample project.
10. Optionally show Floci persistence for synthetic audit metadata.
11. Finish with a data-flow diagram, known limitations, and the approval needed to connect a company-managed endpoint.

Do not use live company code for the first demo. If a later company pilot uses internal code, run it only inside an explicitly approved company environment.

---

## 13. Success metrics

Record measured values rather than promising improvements in advance:

- Percentage of mock primary rate-limit events successfully handled by an allowed fallback.
- Percentage of tests passing in mock mode without external network access.
- Time to detect/classify an error and select a fallback.
- Fallback latency and local-model latency, reported separately.
- Number of blocked unauthorized routing attempts.
- Number of prompt/output contents present in audit logs (target: zero by default).
- Local-model quality on a small, documented synthetic coding test set.
- Estimated provider cost only for approved external integration tests; mock tests should incur no model-provider cost.

---

## 14. Go/no-go checklist

Before the prototype is connected to a real company endpoint, answer **yes** to all relevant questions:

- [ ] Is the repository location and cross-device workflow permitted by company policy?
- [ ] Does the corporate profile work without Ollama, ChromaDB, Floci, and personal API keys?
- [ ] Are all example prompts and source files synthetic or explicitly approved?
- [ ] Are external providers allowlisted and never selected implicitly?
- [ ] Is fallback limited to approved error types and approved data routes?
- [ ] Are authentication and policy failures denied rather than rerouted?
- [ ] Are prompts, source code, credentials, and full outputs excluded from logs by default?
- [ ] Are credentials excluded from Git and loaded from an approved secret mechanism?
- [ ] Are mock-only tests repeatable offline?
- [ ] Has the security/AI platform team approved the real endpoint, use cases, budgets, retention, identity, and network controls?

If the last item is not approved, keep the application in mock mode and continue using Copilot only as authorized for development assistance.

---

## 15. Official documentation

- GitHub Copilot model availability and custom models: <https://docs.github.com/en/copilot/how-tos/copilot-on-github/set-up-copilot/configure-access-to-ai-models>
- VS Code language models and BYOK/custom endpoints: <https://code.visualstudio.com/docs/copilot/customization/language-models>
- GitHub Copilot SDK BYOK; provider quotas and limitations: <https://docs.github.com/en/copilot/how-tos/copilot-sdk/auth/byok>
- LiteLLM routing and reliability: <https://docs.litellm.ai/docs/routing>
- Ollama Windows/local API: <https://ollama.com/blog/windows-preview>
- ChromaDB persistent client: <https://docs.trychroma.com/docs/run-chroma/cloud-client>
- Floci local AWS emulator: <https://github.com/floci-io/floci>
