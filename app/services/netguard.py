"""Outbound-request guard (SSRF protection).

A scraper is an SSRF machine by design: it fetches user-supplied URLs from
the server's network position. This module makes every outbound HTTP client
refuse destinations that resolve to loopback, private, link-local, or
otherwise non-public addresses — so ``http://169.254.169.254/latest/...``
(cloud metadata), ``http://10.0.0.5/admin``, and redirect chains that end on
an internal host are all rejected before a connection is made.

Two layers, both reusing the same address policy:

1. :func:`event_hooks` — validates every request URL at the httpx layer,
   including each hop of a redirect chain, and yields a clean error early.
2. A pinned network backend (:func:`guarded_async_client`) — validates at the
   real socket-connect seam and connects only to the exact public IP it
   validated. This closes the DNS-rebinding TOCTOU: because the address that
   is checked *is* the address that is dialed (one resolution, no second
   lookup), an attacker cannot answer "public" for the check and "private"
   for the connection. TLS still verifies against the original hostname (SNI
   comes from the request origin, not the dialed IP), so HTTPS is unaffected.

Use :func:`guarded_async_client` for every outbound ``httpx`` fetch. The
rendered (Playwright) path validates the top-level URL and intercepts
subresource requests through the same check.

Deliberately opt-out: set ``allow_private_networks=true`` only when you
intend to scrape hosts on your own internal network.
"""
from __future__ import annotations

import asyncio
import ipaddress
import socket
from urllib.parse import urlparse

import httpcore
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


async def _resolve_public(host: str) -> list[str]:
    """Resolve *host*, requiring every answer to be a public address.

    Refusing when *any* returned address is non-public means a hostname that
    resolves to ``[public, 10.0.0.1]`` is rejected rather than gambling on
    which record the OS resolver hands the real connection.
    """
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
    return addresses


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
    await _resolve_public(host)


async def _request_hook(request: httpx.Request) -> None:
    await check_url(str(request.url))


def event_hooks() -> dict[str, list]:
    """httpx event hooks validating every request, including redirect hops."""
    return {"request": [_request_hook]}


class _GuardedBackend(httpcore.AsyncNetworkBackend):
    """Wraps httpcore's real backend so the TCP connection is pinned to a
    validated public IP. ``connect_tcp`` receives the origin *hostname*; we
    resolve+validate it and dial the resulting IP directly, so the address
    that was checked is exactly the one connected to — no second lookup for a
    rebinding attacker to poison. TLS/SNI still use the hostname (httpcore
    takes ``server_hostname`` from the request origin, not this dial target).
    """

    def __init__(self, inner: httpcore.AsyncNetworkBackend):
        self._inner = inner

    async def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,
        local_address: str | None = None,
        socket_options=None,  # noqa: ANN001 - httpcore SOCKET_OPTION iterable
    ) -> httpcore.AsyncNetworkStream:
        dial_host = host
        if not get_settings().allow_private_networks:
            addresses = await _resolve_public(host)
            dial_host = addresses[0]  # a validated, public address
        return await self._inner.connect_tcp(
            dial_host,
            port,
            timeout=timeout,
            local_address=local_address,
            socket_options=socket_options,
        )

    async def connect_unix_socket(self, *args, **kwargs):  # noqa: ANN002, ANN003
        # Never reached via user URLs (we never configure a UDS pool), but a
        # local unix socket is not a public destination — refuse on principle.
        raise PrivateAddressError("Unix-socket connections are not permitted")

    async def sleep(self, seconds: float) -> None:
        await self._inner.sleep(seconds)


def guarded_async_client(**kwargs) -> httpx.AsyncClient:  # noqa: ANN003
    """An ``httpx.AsyncClient`` hardened against SSRF on every connection.

    Combines both layers: the request event hook (validates each URL/redirect
    hop, clean errors) and the pinned backend (connects only to a validated
    public IP, closing the DNS-rebinding window). Use this for ALL outbound
    fetches instead of constructing ``httpx.AsyncClient`` directly.
    """
    hooks = kwargs.pop("event_hooks", None) or event_hooks()
    transport = httpx.AsyncHTTPTransport()
    transport._pool._network_backend = _GuardedBackend(transport._pool._network_backend)
    return httpx.AsyncClient(transport=transport, event_hooks=hooks, **kwargs)
