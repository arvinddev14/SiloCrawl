import pytest
import respx
from httpx import Response

from app.services import robots
from app.services.robots import RobotsDisallowedError

ROBOTS_TXT = """\
User-agent: *
Disallow: /private/
"""


@pytest.fixture(autouse=True)
def clear_robots_cache():
    robots._cache.clear()
    yield
    robots._cache.clear()


@respx.mock
async def test_disallowed_path_raises():
    respx.get("https://example.com/robots.txt").mock(
        return_value=Response(200, text=ROBOTS_TXT)
    )
    with pytest.raises(RobotsDisallowedError):
        await robots.check("https://example.com/private/page")


@respx.mock
async def test_allowed_path_passes():
    respx.get("https://example.com/robots.txt").mock(
        return_value=Response(200, text=ROBOTS_TXT)
    )
    await robots.check("https://example.com/public")


@respx.mock
async def test_missing_robots_allows_everything():
    respx.get("https://example.com/robots.txt").mock(return_value=Response(404))
    await robots.check("https://example.com/private/page")


@respx.mock
async def test_unreachable_robots_allows_everything():
    import httpx

    respx.get("https://example.com/robots.txt").mock(
        side_effect=httpx.ConnectError("down")
    )
    await robots.check("https://example.com/private/page")


@respx.mock
async def test_robots_fetch_is_cached_per_domain():
    route = respx.get("https://example.com/robots.txt").mock(
        return_value=Response(200, text=ROBOTS_TXT)
    )
    await robots.check("https://example.com/a")
    await robots.check("https://example.com/b")
    assert route.call_count == 1
