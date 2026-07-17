"""Fast URL discovery: try sitemap.xml first, fall back to homepage links."""
from __future__ import annotations

from urllib.parse import urlparse

import httpx
from selectolax.parser import HTMLParser

from app.core.config import get_settings
from app.models.schemas import MapRequest, MapResult
from app.services import fetcher, netguard

settings = get_settings()


def _same_site(url: str, base: str, include_subdomains: bool) -> bool:
    h1, h2 = urlparse(url).netloc, urlparse(base).netloc
    if include_subdomains:
        root = ".".join(h2.split(".")[-2:])
        return h1.endswith(root)
    return h1 == h2


async def _from_sitemap(base: str) -> list[str]:
    root = f"{urlparse(base).scheme}://{urlparse(base).netloc}"
    urls: list[str] = []
    async with httpx.AsyncClient(
        timeout=settings.request_timeout,
        headers={"User-Agent": settings.user_agent},
        event_hooks=netguard.event_hooks(),
    ) as client:
        for path in ("/sitemap.xml", "/sitemap_index.xml"):
            try:
                r = await client.get(root + path, follow_redirects=True)
                if r.status_code == 200 and ("<urlset" in r.text or "<sitemapindex" in r.text):
                    tree = HTMLParser(r.text)
                    urls += [n.text() for n in tree.css("loc") if n.text()]
            except httpx.HTTPError:
                continue
    return urls


async def map_site(req: MapRequest) -> MapResult:
    base = str(req.url)
    found: set[str] = set(await _from_sitemap(base))

    # Always include homepage links as a fallback / supplement.
    # Goes through fetch() so robots.txt + politeness apply (best-effort anyway).
    try:
        resp = await fetcher.fetch(base)
        tree = HTMLParser(resp.html)
        from app.services.cleaner import _extract_links

        found.update(_extract_links(tree, resp.url))
    except Exception:  # noqa: BLE001 - mapping is best-effort
        pass

    links = [
        u
        for u in found
        if _same_site(u, base, req.include_subdomains)
        and (req.search is None or req.search.lower() in u.lower())
    ]
    links = sorted(set(links))[: req.limit]
    return MapResult(base_url=base, links=links, count=len(links))
