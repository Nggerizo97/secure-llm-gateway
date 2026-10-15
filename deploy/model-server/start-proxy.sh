#!/usr/bin/env bash
# Start the token-checking TLS proxy in front of Ollama on the WSL "model server" (machine B).
# Generates the proxy token on first run (stored only in ~/.config/secure-llm-gateway, mode 600).
#
#   bash deploy/model-server/start-proxy.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONFIG_DIR="$HOME/.config/secure-llm-gateway"
TOKEN_FILE="$CONFIG_DIR/model-proxy-token"

command -v caddy >/dev/null 2>&1 || { echo "caddy is not installed; run setup.sh first" >&2; exit 1; }

# Ollama must listen on loopback only, so this proxy is the only way in
listeners="$(ss -ltn | awk 'NR > 1 {print $4}' | grep -E ':11434$' || true)"
if echo "$listeners" | grep -Eq '^(0\.0\.0\.0|\*|\[::\]):11434$'; then
  echo "Ollama is listening on all interfaces. Re-run setup.sh to pin it to 127.0.0.1." >&2
  exit 1
fi
if ! echo "$listeners" | grep -Eq '^127\.0\.0\.1:11434$'; then
  echo "Ollama is not listening on 127.0.0.1:11434. Start it with: sudo systemctl start ollama" >&2
  exit 1
fi

mkdir -p "$CONFIG_DIR"
chmod 700 "$CONFIG_DIR"
if [[ ! -s "$TOKEN_FILE" ]]; then
  (umask 077 && openssl rand -hex 32 > "$TOKEN_FILE")
  echo "Generated a new proxy token in $TOKEN_FILE"
fi

MODEL_SERVER_IP="$(ip -4 -o addr show eth0 | awk '{print $4}' | cut -d/ -f1 | head -n1)"
[[ -n "$MODEL_SERVER_IP" ]] || { echo "Could not determine the eth0 address" >&2; exit 1; }
MODEL_PROXY_TOKEN="$(cat "$TOKEN_FILE")"
export MODEL_SERVER_IP MODEL_PROXY_TOKEN

echo "Model server proxy: https://$MODEL_SERVER_IP:8443 (only POST /api/generate with the token)"
echo "Then, on Windows from the repo root:  . .\\deploy\\gateway\\use-wsl-model-server.ps1"
echo "Press Ctrl+C to stop."

# The adapted config contains the token. Caddy 2.6 (Ubuntu's package) would autosave it to
# ~/.config/caddy/autosave.json and has no Caddyfile option to stop that, so adapt to JSON in
# memory, turn persistence off, and hand it to Caddy on stdin. Also remove any earlier autosave.
rm -f "$HOME/.config/caddy/autosave.json"
caddy adapt --config "$SCRIPT_DIR/Caddyfile" --adapter caddyfile \
  | python3 -c 'import json, sys; c = json.load(sys.stdin); c.setdefault("admin", {}).setdefault("config", {})["persist"] = False; json.dump(c, sys.stdout)' \
  | caddy run --config /dev/stdin
