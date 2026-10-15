#!/usr/bin/env bash
# One-time setup of the WSL "model server" (machine B).
# Installs Caddy, ufw, tcpdump and zstd from apt and Ollama from its official install script, pins Ollama
# to loopback with debug logging off, and downloads the model while outbound internet is still open.
# Review before running: it uses sudo.
#
#   bash deploy/model-server/setup.sh [model]      (default model: qwen2.5-coder:1.5b)
set -euo pipefail

MODEL="${1:-qwen2.5-coder:1.5b}"

sudo apt-get update
# zstd is required by the Ollama installer to extract its archive
sudo apt-get install -y caddy ufw tcpdump zstd

# The packaged Caddy service serves a welcome page on :80; this demo runs its own proxy instead
sudo systemctl disable --now caddy 2>/dev/null || true

if ! command -v ollama >/dev/null 2>&1; then
  curl -fsSL https://ollama.com/install.sh | sh
fi

# Loopback only (the proxy is the only way in) and no debug logging (debug mode can log prompts)
sudo mkdir -p /etc/systemd/system/ollama.service.d
sudo tee /etc/systemd/system/ollama.service.d/secure-llm-gateway.conf >/dev/null <<'EOF'
[Service]
Environment="OLLAMA_HOST=127.0.0.1:11434"
Environment="OLLAMA_DEBUG=0"
Environment="OLLAMA_NOHISTORY=1"
EOF
sudo systemctl daemon-reload
sudo systemctl enable ollama
sudo systemctl restart ollama

for _ in $(seq 1 30); do
  curl -fsS http://127.0.0.1:11434/api/version >/dev/null 2>&1 && break
  sleep 1
done
ollama pull "$MODEL"

echo
echo "Setup complete. Model: $MODEL"
echo "Next: bash deploy/model-server/start-proxy.sh"
