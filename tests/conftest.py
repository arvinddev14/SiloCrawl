import httpx
import pytest

from app.core.config import get_settings
from app.db import init_db
from app.db.base import get_engine, get_sessionmaker
from app.llm import router as router_module
from app.main import app
from app.services import netguard


@pytest.fixture(autouse=True)
def public_dns(monkeypatch):
    """Keep tests hermetic: the SSRF guard must never do real DNS lookups.
    Everything resolves public unless a test re-patches to a private address."""

    async def fake_resolve(host: str) -> list[str]:
        return ["93.184.216.34"]

    monkeypatch.setattr(netguard, "_resolve", fake_resolve)


@pytest.fixture
async def temp_db(tmp_path, monkeypatch):
    """Point the persistence layer at a throwaway SQLite file."""
    db_file = tmp_path / "test.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{db_file.as_posix()}")
    for fn in (get_settings, get_engine, get_sessionmaker):
        fn.cache_clear()
    router_module.invalidate_promotions()  # cache must not leak across DBs
    await init_db()
    yield
    await get_engine().dispose()
    for fn in (get_settings, get_engine, get_sessionmaker):
        fn.cache_clear()
    router_module.invalidate_promotions()


@pytest.fixture
async def client(temp_db):
    """ASGI test client. Outbound httpx (the app's own fetches) is left for
    respx to mock — ASGITransport bypasses respx, so app requests reach here."""
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
