#!/usr/bin/env bash
# Evidence that the model server (machine B) keeps no copy of prompts and receives them only encrypted.
#
#   start : creates a unique canary string, a timestamp marker, and starts a packet capture on eth0:8443
#           -> put the canary in prompts sent through the gateway on Windows
#   check : stops the capture and searches the capture, every file changed on this machine's disk
#           since `start`, and the system journal for the canary
#
#   bash deploy/model-server/evidence.sh start|check
#
# Limitation: this cannot inspect RAM. The model necessarily holds the prompt in memory while answering.
set -euo pipefail

DIR="$HOME/.cache/secure-llm-gateway"
CANARY_FILE="$DIR/canary"
MARKER="$DIR/evidence-start"
PCAP="/tmp/secure-llm-gateway-demo.pcap"
PIDFILE="$DIR/capture.pid"
TCPDUMP=(tcpdump -i eth0 -U -Z root -w "$PCAP" tcp port 8443)

mkdir -p "$DIR"
chmod 700 "$DIR"

case "${1:-}" in
  start)
    echo "CANARY-$(openssl rand -hex 8)" > "$CANARY_FILE"
    sudo -v
    touch "$MARKER"
    sudo rm -f "$PCAP"
    sudo "${TCPDUMP[@]}" >/dev/null 2>&1 &
    echo $! > "$PIDFILE"  # sudo's pid; sudo relays signals to tcpdump
    sleep 1
    echo "Capture running on eth0, port 8443."
    echo "Canary: $(cat "$CANARY_FILE")"
    echo "Include the canary in prompts sent through the gateway, make sure some reach the fallback,"
    echo "then run: bash deploy/model-server/evidence.sh check"
    ;;
  check)
    [[ -s "$CANARY_FILE" && -f "$MARKER" ]] || { echo "Run 'evidence.sh start' first" >&2; exit 1; }
    # The canary is always read from $CANARY_FILE (grep -f), never passed as an argument:
    # sudo logs every command line to auth.log and the journal, which would plant the canary
    # in the very logs being searched.
    [[ -s "$PIDFILE" ]] && sudo kill -INT "$(cat "$PIDFILE")" 2>/dev/null || true
    rm -f "$PIDFILE"
    sleep 1

    failed=0
    report() { if [[ "$2" == "ok" ]]; then echo "PASS  $1"; else echo "FAIL  $1"; failed=1; fi; }

    packets="$(sudo tcpdump -r "$PCAP" 2>/dev/null | wc -l)"
    report "Gateway traffic was captured ($packets packets on eth0:8443)" "$([[ "$packets" -gt 0 ]] && echo ok)"
    report "Canary absent from captured traffic (TLS-encrypted on the wire)" \
      "$(sudo grep -qaF -f "$CANARY_FILE" "$PCAP" && echo found || echo ok)"

    mapfile -t changed < <(sudo find / -xdev -type f -newer "$MARKER" \
      -not -path "$DIR/*" -not -path "$PCAP" -not -path '/proc/*' 2>/dev/null)
    hits=""
    if ((${#changed[@]})); then
      hits="$(printf '%s\0' "${changed[@]}" | sudo xargs -0 grep -laF -f "$CANARY_FILE" 2>/dev/null || true)"
    fi
    report "Canary absent from all ${#changed[@]} files changed on disk since start" "$([[ -z "$hits" ]] && echo ok)"
    [[ -n "$hits" ]] && echo "$hits" | sed 's/^/      found in: /'

    since="@$(date -r "$MARKER" +%s)"
    journal_hits="$(sudo journalctl --since "$since" --no-pager 2>/dev/null | grep -aF -f "$CANARY_FILE" || true)"
    report "Canary absent from the system journal (Ollama service logs)" "$([[ -z "$journal_hits" ]] && echo ok)"
    [[ -n "$journal_hits" ]] && echo "$journal_hits" | cut -c1-200 | sed 's/^/      line: /'

    echo
    echo "Files changed since start (for transparency):"
    printf '  %s\n' "${changed[@]:0:50}"
    ((${#changed[@]} > 50)) && echo "  ... and $((${#changed[@]} - 50)) more"
    exit "$failed"
    ;;
  *)
    echo "usage: $0 start|check" >&2
    exit 2
    ;;
esac
