# Two-Machine Demo: Windows Gateway + WSL Model Server

Shows the core requirement end to end: **when the company provider runs out of tokens, requests fail over to an approved self-hosted model reached only over TLS with a token, and the model server keeps no copy of the prompts.**

| Role | Here | Stands in for |
|---|---|---|
| Machine A — gateway | Windows (this repo, PowerShell) | Company laptop / company-hosted gateway |
| Company provider | `mock_provider` on `127.0.0.1:8900` — real HTTP, real 429 when its token budget runs out | The company's contracted LLM |
| Machine B — model server | WSL2 Ubuntu: Ollama on loopback, behind a Caddy proxy (TLS + token) on the WSL address | Model server in the company VPC |

Read [requirements.md](requirements.md) first, especially the honesty constraint: WSL runs on the same physical computer, and the model server necessarily processes prompts in memory. The demo proves the **architecture and controls**. Use synthetic prompts only.

This guide assumes WSL2's default NAT networking (WSL gets its own `172.x` address). If you enabled `networkingMode=mirrored` in `.wslconfig`, this layout does not apply.

---

## 1. One-time setup in WSL (machine B)

Open an Ubuntu terminal and go to the repo:

```bash
cd /mnt/c/Users/erizo/OneDrive/Documentos/codes/Codes_Projects/secure-llm-gateway
```

Review, then run, the setup script. It uses `sudo`, installs Caddy, ufw and tcpdump from apt, installs Ollama with its official script, pins Ollama to `127.0.0.1` with debug logging off, and downloads the model:

```bash
bash deploy/model-server/setup.sh
```

The default model is `qwen2.5-coder:1.5b` (about 1 GB, fine on CPU). Pass another name as the first argument if you prefer, and use the same name in steps 3 and 4.

## 2. Start the model server proxy (WSL terminal 1)

```bash
bash deploy/model-server/start-proxy.sh
```

It refuses to start unless Ollama listens on loopback only, generates the proxy token on first run (`~/.config/secure-llm-gateway/model-proxy-token`, mode 600), and serves `https://<WSL address>:8443`, forwarding only `POST /api/generate` with the right token. Leave it running.

## 3. Lock down and verify machine B (WSL terminal 2)

```bash
bash deploy/model-server/firewall.sh secure
```

Inbound traffic is now accepted only from the Windows host, on port 8443.

```bash
bash deploy/model-server/verify.sh
```

Every line should say `PASS`: Ollama loopback-only, the certificate verifies, missing or wrong tokens get 403, admin endpoints (`/api/pull`, `/api/tags`) get 403 even with the token, plain HTTP is not served, and a valid request gets an answer from the model.

## 4. Start the company provider and point the gateway at WSL (Windows)

Windows terminal 1, from the repo root:

```powershell
python -m mock_provider.service --tokens-per-minute 60
```

Windows terminal 2, from the repo root:

```powershell
. .\deploy\gateway\use-wsl-model-server.ps1
```

This reads the WSL address, the proxy token (straight into an environment variable, never printed) and the proxy's CA certificate, and configures the gateway for this PowerShell session: primary `openai_compat` → mock company provider, fallback `ollama` → WSL over HTTPS, simulation disabled.

## 5. Run out of tokens and fail over (Windows terminal 2)

```powershell
python -m app.cli ask "Explain exponential backoff in one sentence." --repeat 6
```

Expected: the first requests show `PRIMARY provider=openai_compat`; once the 60-token budget is spent the company provider returns a real HTTP 429 and the rest show `FALLBACK (rate_limit) provider=ollama` with an answer from the WSL model. Wait a minute and the primary serves requests again.

Show the audit trail (metadata only, no prompts):

```powershell
python -m app.cli audit-report
```

## 6. Model server cannot send data anywhere (WSL terminal 2)

```bash
bash deploy/model-server/firewall.sh lockdown
```

```bash
curl -sS --max-time 5 https://example.com -o /dev/null || echo "outbound blocked"
```

Run step 5 again on Windows: fallback answers still arrive (they are replies on connections the gateway opened), but machine B cannot open any connection of its own.

## 7. Evidence: prompts are encrypted on the wire and not stored (both)

WSL terminal 2:

```bash
bash deploy/model-server/evidence.sh start
```

It prints a canary such as `CANARY-1a2b3c4d5e6f7a8b` and starts a packet capture. On Windows, send prompts containing it, enough to exhaust the budget so some reach machine B:

```powershell
python -m app.cli ask "Review this synthetic function. Reference CANARY-1a2b3c4d5e6f7a8b" --repeat 6
```

Back in WSL:

```bash
bash deploy/model-server/evidence.sh check
```

Expected `PASS` lines: traffic was captured; the canary is absent from the capture (TLS); absent from every file changed on machine B's disk since `start`; absent from the system journal (Ollama service logs). The script also lists the changed files for transparency.

On Windows, confirm the gateway's audit database has no prompt text either:

```powershell
Select-String -Path data\audit.db -Pattern "CANARY-" -SimpleMatch -Quiet
```

Expected: `False`.

## 8. Show what the gateway refuses (Windows terminal 2)

Make one change, then run `python -m app.cli ask "x" --repeat 6`. Once the budget is spent, the fallback requests should print `BLOCKED` with the stated category:

| Change | Command | Expected |
|---|---|---|
| Plain HTTP to the model server | `$env:OLLAMA_BASE_URL = $env:OLLAMA_BASE_URL -replace '^https','http'` | `endpoint_denied` |
| Missing token | `Remove-Item Env:OLLAMA_API_KEY` | `endpoint_denied` |
| Public address | `$env:OLLAMA_BASE_URL = "https://8.8.8.8:8443"` | `endpoint_denied` |
| Wrong CA | `Remove-Item Env:OLLAMA_CA_BUNDLE` | `service_unavailable` (certificate rejected) |

Re-run `. .\deploy\gateway\use-wsl-model-server.ps1` to restore the settings between changes.

## 9. Clean up

WSL:

```bash
bash deploy/model-server/firewall.sh open
```

Stop the proxy with Ctrl+C. To remove the firewall entirely: `sudo ufw disable`. To stop the model service: `sudo systemctl stop ollama`.

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| WSL address changed (after `wsl --shutdown` or a reboot) | Restart `start-proxy.sh`, then re-run `use-wsl-model-server.ps1`. |
| `ufw enable` fails inside WSL | Update WSL (`wsl --update`) and retry; the WSL2 kernel needs netfilter support. |
| Port 11434 already in use | Ollama for Windows may be running too; it is not used by this demo. Stop it or keep the WSL service on loopback as configured. |
| Certificate errors from the gateway | Re-run `use-wsl-model-server.ps1` to re-export Caddy's CA certificate. |
| `$'\r': command not found` in WSL | The scripts got Windows line endings; `.gitattributes` prevents this on fresh checkouts. Run `sed -i 's/\r$//' deploy/model-server/*.sh`. |

## Known limitations

- Same physical computer: WSL is a separate VM and network, not a separate machine.
- RAM is not inspected; the model must hold the prompt in memory to answer.
- The proxy compares the token as a plain header match (not constant-time).
- The mock company provider stands in for a real company provider; with approval, point `OPENAI_COMPAT_*` at the company's real endpoint instead.
