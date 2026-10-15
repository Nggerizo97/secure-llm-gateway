#!/usr/bin/env bash
# Firewall for the WSL "model server" (machine B).
#
#   secure   : inbound only from the Windows host to the proxy port (8443); outbound allowed
#   lockdown : also block every new outbound connection, so the model server cannot send data anywhere
#              (replies to the gateway still flow because they belong to established connections)
#   open     : allow outbound again (e.g. to pull another model)
#   status   : show the current rules
#
#   bash deploy/model-server/firewall.sh secure|lockdown|open|status
set -euo pipefail

HOST_IP="$(ip route | awk '/^default/ {print $3; exit}')"
PORT=8443

case "${1:-status}" in
  secure)
    sudo ufw --force reset >/dev/null
    sudo ufw default deny incoming
    sudo ufw default allow outgoing
    sudo ufw allow from "$HOST_IP" to any port "$PORT" proto tcp comment 'gateway (Windows host) -> model proxy'
    sudo ufw --force enable
    ;;
  lockdown)
    sudo ufw default deny outgoing
    ;;
  open)
    sudo ufw default allow outgoing
    ;;
  status)
    ;;
  *)
    echo "usage: $0 secure|lockdown|open|status" >&2
    exit 2
    ;;
esac

sudo ufw status verbose
