# SiloCrawl

An open-source, LLM-powered web scraping toolkit — a clean-room alternative to Firecrawl.

## Features (v1)

- **Scrape** — fetch a single URL and return clean Markdown + metadata. Optional JS rendering.
- **Crawl** — recursively follow links across a site with depth/page limits, returned as a batch.
- **Map** — fast URL discovery for a domain (sitemap + link extraction).
- **Extract** — LLM-powered structured extraction against a user-supplied JSON Schema.

Crawl jobs run asynchronously as in-process background tasks with their state in
SQLite; scrape/map/extract run inline for low latency. No external queue or
worker process is required.

## Architecture

```
 API (FastAPI)
   │
   ├── /scrape   ── inline ─────┐
   ├── /map      ── inline ─────┤
   ├── /extract  ── inline ─────┤
   └── /crawl    ── background task ─> SQLite (job state)
                                          │
   Fetcher (httpx | Playwright) ─> Cleaner (trafilatura/readability ─> markdown)
                                          │
                                  Extractor (LLM + JSON schema)
```

## Quickstart

```bash
# 1. Install
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
playwright install chromium      # only needed for JS rendering

# 2. Configure
cp .env.example .env             # set HF_API_KEY, HF_ENDPOINT_URL, etc.

# 3. Start the API (crawl jobs run in-process — no worker needed)
uvicorn app.main:app --reload
```

Or just `docker compose up` — this brings up the API (`localhost:8000`) and the
frontend (`localhost:3000`). Redis is included but optional: it backs only the
opt-in response cache and API-key rate limiting.

> **Config note:** SiloCrawl runs an open-source LLM (`openai/gpt-oss-120b`) through a
> HuggingFace Inference Endpoint — set `HF_API_KEY` and `HF_ENDPOINT_URL` in `.env`
> (see `.env.example`). `.env` is gitignored; rotate your key if it has ever been shared.

## Example

```bash
# Scrape one page to markdown
curl -X POST localhost:8000/v1/scrape \
  -H 'content-type: application/json' \
  -d '{"url": "https://example.com", "formats": ["markdown"]}'

# Structured LLM extraction
curl -X POST localhost:8000/v1/extract \
  -H 'content-type: application/json' \
  -d '{
    "url": "https://example.com",
    "schema": {
      "type": "object",
      "properties": {
        "title": {"type": "string"},
        "summary": {"type": "string"}
      }
    }
  }'
```

## Security

Safe-by-default for self-hosting, but read this before exposing the API
beyond localhost:

- **Turn auth on for any network-exposed deployment**: set `AUTH_ENABLED=true`
  and `API_KEYS=<comma-separated keys>`. Without it, anyone who can reach the
  port can scrape (and pay for LLM calls) through your server.
- **SSRF guard (on by default)**: every outbound fetch — scrape, map, extract,
  crawl, documents, robots.txt, and each redirect hop — refuses URLs that
  resolve to loopback, private, or link-local addresses (cloud metadata
  endpoints included). Rendered pages get the same check on subresources. Set
  `ALLOW_PRIVATE_NETWORKS=true` only to deliberately scrape your own internal
  network.
- **Size caps**: page bodies are capped at `FETCH_MAX_BYTES` (10 MB) and
  documents at `DOCUMENT_MAX_BYTES` (25 MB), enforced while streaming — a
  hostile server can't balloon memory.
- **Redis** ships unauthenticated; docker-compose publishes it on loopback
  only. Never map it to a public interface.
- Report vulnerabilities via GitHub issues (or privately via the email on the
  profile) — please include reproduction steps.

## License

MIT — see LICENSE.
