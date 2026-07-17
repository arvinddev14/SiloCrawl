import time

from app.services.throttle import DomainThrottle


async def test_same_domain_requests_are_spaced():
    t = DomainThrottle()
    start = time.monotonic()
    await t.wait("https://example.com/a", min_delay=0.2)
    await t.wait("https://example.com/b", min_delay=0.2)
    assert time.monotonic() - start >= 0.2


async def test_different_domains_do_not_block_each_other():
    t = DomainThrottle()
    start = time.monotonic()
    await t.wait("https://a.com/", min_delay=0.5)
    await t.wait("https://b.com/", min_delay=0.5)
    assert time.monotonic() - start < 0.4


async def test_zero_delay_never_sleeps():
    t = DomainThrottle()
    start = time.monotonic()
    for _ in range(3):
        await t.wait("https://example.com/", min_delay=0)
    assert time.monotonic() - start < 0.1
