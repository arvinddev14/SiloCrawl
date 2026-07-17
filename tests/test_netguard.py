import httpcore
import httpx
import pytest
import respx

from app.core.config import get_settings
from app.services import documents, fetcher, netguard
from app.services.documents import DocumentTooLargeError
from app.services.fetcher import FetchTooLargeError
from app.services.netguard import PrivateAddressError


def _resolve_to(monkeypatch, *ips: str) -> None:
    async def fake(host: str) -> list[str]:
        return list(ips)

    monkeypatch.setattr(netguard, "_resolve", fake)


class _FakeInner(httpcore.AsyncNetworkBackend):
    """Records what the pinned backend actually dials, without opening a socket."""

    def __init__(self):
        self.dialed: tuple[str, int] | None = None

    async def connect_tcp(self, host, port, timeout=None, local_address=None,
                          socket_options=None):
        self.dialed = (host, port)
        return object()  # a real AsyncNetworkStream is never used in these tests

    async def connect_unix_socket(self, *args, **kwargs):
        raise NotImplementedError

    async def sleep(self, seconds):
        pass


# ---------- address classification ----------

@pytest.mark.parametrize(
    "ip",
    [
        "127.0.0.1",          # loopback
        "10.0.0.5",           # RFC1918
        "172.16.3.4",         # RFC1918
        "192.168.1.1",        # RFC1918
        "169.254.169.254",    # link-local / cloud metadata
        "100.64.0.1",         # CGNAT shared space
        "0.0.0.0",
        "::1",                # v6 loopback
        "fc00::1",            # v6 unique-local
        "fe80::1",            # v6 link-local
        "::ffff:10.0.0.1",    # v4 private hidden in a mapped v6
    ],
)
def test_non_public_addresses_blocked(ip):
    assert netguard.is_public_address(ip) is False


@pytest.mark.parametrize("ip", ["93.184.216.34", "8.8.8.8", "2606:2800:220:1::1"])
def test_public_addresses_allowed(ip):
    assert netguard.is_public_address(ip) is True


# ---------- check_url ----------

async def test_private_host_rejected(monkeypatch):
    _resolve_to(monkeypatch, "10.0.0.5")
    with pytest.raises(PrivateAddressError):
        await netguard.check_url("http://internal.corp/admin")


async def test_mixed_resolution_rejected(monkeypatch):
    # DNS answers with one public and one private record -> still refused
    _resolve_to(monkeypatch, "93.184.216.34", "192.168.0.10")
    with pytest.raises(PrivateAddressError):
        await netguard.check_url("http://sneaky.example")


async def test_metadata_endpoint_rejected(monkeypatch):
    _resolve_to(monkeypatch, "169.254.169.254")
    with pytest.raises(PrivateAddressError):
        await netguard.check_url("http://169.254.169.254/latest/meta-data/")


async def test_non_http_scheme_rejected():
    with pytest.raises(PrivateAddressError):
        await netguard.check_url("file:///etc/passwd")


async def test_public_host_allowed(monkeypatch):
    _resolve_to(monkeypatch, "93.184.216.34")
    await netguard.check_url("https://example.com/")  # no raise


async def test_opt_out_allows_private(monkeypatch):
    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "allow_private_networks", True)
    _resolve_to(monkeypatch, "127.0.0.1")
    await netguard.check_url("http://localhost:8000/")  # no raise


# ---------- wired into the fetchers ----------

async def test_fetch_static_blocks_private(monkeypatch):
    _resolve_to(monkeypatch, "10.1.2.3")
    with pytest.raises(PrivateAddressError):
        await fetcher.fetch_static("http://intranet.local/")


@respx.mock
async def test_redirect_to_private_blocked(monkeypatch):
    # First hop is public; the redirect target resolves private.
    async def fake(host: str) -> list[str]:
        return ["10.0.0.9"] if host == "internal.test" else ["93.184.216.34"]

    monkeypatch.setattr(netguard, "_resolve", fake)
    respx.get("https://example.com/").mock(
        return_value=httpx.Response(302, headers={"location": "http://internal.test/"})
    )
    with pytest.raises(PrivateAddressError):
        await fetcher.fetch_static("https://example.com/")


@respx.mock
async def test_fetch_static_size_cap(monkeypatch):
    monkeypatch.setattr(fetcher.settings, "fetch_max_bytes", 10)
    respx.get("https://example.com/big").mock(
        return_value=httpx.Response(200, content=b"x" * 50)
    )
    with pytest.raises(FetchTooLargeError):
        await fetcher.fetch_static("https://example.com/big")


@respx.mock
async def test_fetch_static_declared_size_cap(monkeypatch):
    monkeypatch.setattr(fetcher.settings, "fetch_max_bytes", 10)
    respx.get("https://example.com/big").mock(
        return_value=httpx.Response(
            200, content=b"x", headers={"content-length": "99999"}
        )
    )
    with pytest.raises(FetchTooLargeError):
        await fetcher.fetch_static("https://example.com/big")


@respx.mock
async def test_document_download_size_cap(monkeypatch):
    monkeypatch.setattr(documents.settings, "document_max_bytes", 10)
    monkeypatch.setattr(documents.settings, "respect_robots", False)
    monkeypatch.setattr(documents.settings, "per_domain_delay", 0.0)
    respx.get("https://example.com/big.pdf").mock(
        return_value=httpx.Response(200, content=b"x" * 50)
    )
    with pytest.raises(DocumentTooLargeError):
        await documents.download("https://example.com/big.pdf")


# ---------- pinned backend: closes the DNS-rebinding TOCTOU ----------

async def test_backend_pins_validated_ip(monkeypatch):
    # The backend dials the validated IP it resolved, not the hostname, so the
    # address checked is exactly the address connected to (no second lookup).
    _resolve_to(monkeypatch, "93.184.216.34")
    inner = _FakeInner()
    await netguard._GuardedBackend(inner).connect_tcp("example.com", 443)
    assert inner.dialed == ("93.184.216.34", 443)


async def test_backend_blocks_private_at_connect(monkeypatch):
    # Even if an earlier check saw a public answer, the backend re-validates at
    # dial time; a rebinding to a private IP is refused and never dialed.
    _resolve_to(monkeypatch, "10.0.0.5")
    inner = _FakeInner()
    with pytest.raises(PrivateAddressError):
        await netguard._GuardedBackend(inner).connect_tcp("rebind.example", 80)
    assert inner.dialed is None


async def test_backend_opt_out_dials_hostname(monkeypatch):
    monkeypatch.setattr(get_settings(), "allow_private_networks", True)
    inner = _FakeInner()
    await netguard._GuardedBackend(inner).connect_tcp("localhost", 6379)
    assert inner.dialed == ("localhost", 6379)


async def test_backend_refuses_unix_socket():
    with pytest.raises(PrivateAddressError):
        await netguard._GuardedBackend(_FakeInner()).connect_unix_socket("/tmp/x.sock")


async def test_guarded_client_installs_pinned_backend():
    client = netguard.guarded_async_client()
    try:
        backend = client._transport._pool._network_backend
        assert isinstance(backend, netguard._GuardedBackend)
    finally:
        await client.aclose()


# ---------- surfaced as HTTP 403 ----------

async def test_scrape_endpoint_returns_403(client, monkeypatch):
    _resolve_to(monkeypatch, "169.254.169.254")
    resp = await client.post(
        "/v1/scrape", json={"url": "http://169.254.169.254/latest/meta-data/"}
    )
    assert resp.status_code == 403
    assert "non-public" in resp.json()["detail"]
