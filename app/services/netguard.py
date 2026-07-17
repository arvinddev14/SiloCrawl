"""Outbound-request guard (SSRF protection).

A scraper is an SSRF machine by design: it fetches user-supplied URLs from
the server's network position. This module makes every outbound HTTP client
refuse destinations that resolve to loopback, private, link-local, or
otherwise non-public addresses — so ``http://169.254.169.254/latest/...``
(cloud metadata), ``http://10.0.0.5/admin``, and redirect chains that end on
an internal host are all rejected before a connection is made.

Wiring: pass :func:`event_hooks` to every ``httpx.AsyncClient``; the hook
re-validates each request in a redirect chain, not just the first URL. The
rendered (Playwright) path validates the top-level URL and intercepts
subresource requests through the same check.

Deliberately opt-out: set ``allow_private_networks=true`` only when you
intend to scrape hosts on your own internal network.

Known limit: validation resolves DNS at request time. An attacker fully
controlling a zero-TTL DNS record could, in principle, answer differently
for the check and the connection (DNS rebinding); pinning connections to the
validated IP would require a custom transport. The guard blocks all standard
SSRF vectors including redirects.
"""
from __future__ import annotations

import asyncio
import ipaddress
import socket
from urllib.parse import urlparse

import httpx

from app.core.config import get_settings

_ALLOWED_SCHEMES = {"http", "https"}


class PrivateAddressError(Exception):
    """The URL points at a private/internal network destination."""


async def _resolve(host: str) -> list[str]:
    loop = asyncio.get_running_loop()
    infos = await loop.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    return [info[4][0] for info in infos]


def is_public_address(ip_str: str) -> bool:
    ip: ipaddress.IPv4Address | ipaddress.IPv6Address = ipaddress.ip_address(ip_str)
    mapped = getattr(ip, "ipv4_mapped", None)  # ::ffff:10.0.0.1 hides a v4 target
    if mapped is not None:
        ip = mapped
    return ip.is_global


async def check_url(url: str) -> None:
    """Raise PrivateAddressError unless *url* resolves only to public addresses."""
    if get_settings().allow_private_networks:
        return
    parsed = urlparse(url)
    if parsed.scheme not in _ALLOWED_SCHEMES:
        raise PrivateAddressError(f"Blocked non-HTTP scheme {parsed.scheme!r}")
    host = parsed.hostname
    if not host:
        raise PrivateAddressError("URL has no host")
    try:
        addresses = await _resolve(host)
    except socket.gaierror as e:
        raise PrivateAddressError(f"Could not resolve host {host!r}") from e
    if not addresses:
        raise PrivateAddressError(f"Host {host!r} resolved to no addresses")
    for address in addresses:
        if not is_public_address(address):
            raise PrivateAddressError(
                f"{host!r} resolves to non-public address {address}; refusing to fetch"
            )


async def _request_hook(request: httpx.Request) -> None:
    await check_url(str(request.url))


def event_hooks() -> dict[str, list]:
    """httpx event hooks validating every request, including redirect hops."""
    return {"request": [_request_hook]}
