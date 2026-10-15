#!/usr/bin/env bash
# Checks the model server's controls from inside WSL while start-proxy.sh is running.
# Prints PASS/FAIL per control and exits non-zero if any check fails.
#
#   bash deploy/model-server/verify.sh [model]      (default model: qwen2.5-coder:1.5b)
set -uo pipefail

MODEL="${1:-qwen2.5-coder:1.5b}"
TOKEN_FILE="$HOME/.config/secure-llm-gateway/model-proxy-token"
CA="$HOME/.local/share/caddy/pki/authorities/local/root.crt"
IP="$(ip -4 -o addr show eth0 | awk '{print $4}' | cut -d/ -f1 | head -n1)"
URL="https://$IP:8443"

[[ -s "$TOKEN_FILE" && -s "$CA" ]] || { echo "Start the proxy first: bash deploy/model-server/start-proxy.sh" >&2; exit 1; }

# Keep the token off the command line: curl reads the header from a private temp file
AUTH_HEADER="$(mktemp)"
trap 'rm -f "$AUTH_HEADER"' EXIT
chmod 600 "$AUTH_HEADER"
printf 'Authorization: Bearer %s\n' "$(cat "$TOKEN_FILE")" > "$AUTH_HEADER"

failed=0
expect() {  # expect <description> <actual> <expected>
  if [[ "$2" == "$3" ]]; then echo "PASS  $1"; else echo "FAIL  $1 (expected $3, got $2)"; failed=1; fi
}
expect_not() {  # expect_not <description> <actual> <unwanted>
  if [[ "$2" != "$3" ]]; then echo "PASS  $1"; else echo "FAIL  $1 (got $2)"; failed=1; fi
}
status() { curl -s -o /dev/null -w '%{http_code}' --max-time 120 "$@"; }

public_listeners="$(ss -ltn | awk 'NR > 1 {print $4}' | grep -E ':11434$' | grep -vcE '^(127\.0\.0\.1|\[::1\]):11434$')"
expect "Ollama listens on loopback only" "$public_listeners" "0"
expect "Ollama unreachable at $IP:11434 (only via proxy)" "$(status --max-time 3 "http://$IP:11434/api/version")" "000"
expect "Proxy certificate verifies against its CA" \
  "$(curl -s -o /dev/null --cacert "$CA" --max-time 5 "$URL/" && echo ok || echo bad)" "ok"
expect "No token -> 403" "$(status --cacert "$CA" -X POST "$URL/api/generate" -d '{}')" "403"
expect "Wrong token -> 403" \
  "$(status --cacert "$CA" -X POST -H 'Authorization: Bearer wrong' "$URL/api/generate" -d '{}')" "403"
expect "Admin endpoint blocked even with token (/api/pull)" \
  "$(status --cacert "$CA" -X POST -H @"$AUTH_HEADER" "$URL/api/pull" -d '{}')" "403"
expect "Model listing blocked even with token (/api/tags)" \
  "$(status --cacert "$CA" -H @"$AUTH_HEADER" "$URL/api/tags")" "403"
expect_not "Plain http to the proxy is not served" "$(status --max-time 5 "http://$IP:8443/api/generate")" "200"
expect "Valid token -> model answers (200)" \
  "$(status --cacert "$CA" -X POST -H @"$AUTH_HEADER" "$URL/api/generate" \
      -d "{\"model\":\"$MODEL\",\"prompt\":\"Reply with OK\",\"stream\":false}")" "200"

exit "$failed"
