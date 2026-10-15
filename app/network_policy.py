"""Network rules for model endpoints. Every check fails closed with a non-retryable policy error."""

import ipaddress
import socket
from typing import List, Union
from urllib.parse import urlparse
from app.providers.base import PolicyViolationError

IPAddress = Union[ipaddress.IPv4Address, ipaddress.IPv6Address]

# CGNAT range used by Tailscale tunnel addresses (not flagged as private by ipaddress)
TUNNEL_NETWORK = ipaddress.ip_network("100.64.0.0/10")


def _deny(message: str) -> PolicyViolationError:
    return PolicyViolationError(message, category="endpoint_denied")


def _resolve(host: str) -> List[IPAddress]:
    if host == "localhost":
        return [ipaddress.ip_address("127.0.0.1")]
    try:
        return [ipaddress.ip_address(host)]
    except ValueError:
        pass
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror as exc:
        raise _deny(f"Model endpoint host '{host}' could not be resolved.") from exc
    return [ipaddress.ip_address(info[4][0].split("%")[0]) for info in infos]


def _is_loopback_url(url: str) -> bool:
    host = urlparse(url).hostname
    return bool(host) and all(a.is_loopback for a in _resolve(host))


def assert_private_model_endpoint(url: str, *, has_api_key: bool, allow_plaintext_tunnel: bool) -> None:
    """A self-hosted model must be on this machine, or on a private/tunnel address behind a token.

    - loopback: allowed as-is (same machine)
    - private LAN / VPN / Tailscale address: requires an API key, and HTTPS unless the operator
      confirms the address is inside an encrypted WireGuard/Tailscale tunnel
    - anything public: denied
    """
    parsed = urlparse(url)
    host = parsed.hostname
    if parsed.scheme not in {"http", "https"} or not host:
        raise _deny(f"Model endpoint '{url}' is not a valid http(s) URL.")

    addresses = _resolve(host)
    if all(a.is_loopback for a in addresses):
        return

    for address in addresses:
        if address.is_unspecified or address.is_link_local:
            raise _deny(f"Model endpoint '{host}' resolves to a non-routable address ({address}).")
        if not (address.is_private or address in TUNNEL_NETWORK):
            raise _deny(
                f"Model endpoint '{host}' resolves to a public address ({address}); "
                "self-hosted models must be reached over a private network or tunnel."
            )

    if not has_api_key:
        raise _deny("Remote model endpoints require an API key (checked by the model server's proxy).")
    if parsed.scheme == "http" and not allow_plaintext_tunnel:
        raise _deny(
            "Remote model endpoints require https. Plain http is only allowed when the address is inside "
            "an encrypted WireGuard/Tailscale tunnel and OLLAMA_ALLOW_PLAINTEXT_TUNNEL=true."
        )


def assert_https_or_loopback(url: str) -> None:
    """External API endpoints must use TLS; plain http is only accepted for a server on this machine."""
    parsed = urlparse(url)
    if not parsed.hostname or parsed.scheme not in {"http", "https"}:
        raise _deny(f"API endpoint '{url}' is not a valid http(s) URL.")
    if parsed.scheme == "http" and not _is_loopback_url(url):
        raise _deny(f"API endpoint '{url}' must use https.")
