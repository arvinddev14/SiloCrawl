# SiloCrawl

An open-source, LLM-powered web scraping toolkit — a clean-room alternative to Firecrawl.

## Features (v1)

- **Scrape** — fetch a single URL and return clean Markdown + metadata. Optional JS rendering.
- **Crawl** — recursively follow links across a site with depth/page limits, returned as a batch.
- **Map** — fast URL discovery for a domain (sitemap + link extraction).
- **Extract** — LLM-powered structured extraction against a user-supplied JSON Schema.

Crawl and large batch jobs run asynchronously on a Redis-backed worker queue; scrape/map/extract
can run inline for low latency.

## Architecture

```
 API (FastAPI)
   │
   ├── /scrape   ── inline ──┐
   ├── /map      ── inline ──┤
   ├── /extract  ── inline ──┤
   └── /crawl    ── enqueue ─┴─> Redis (arq) ─> Worker
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
cp .env.example .env             # set HF_API_KEY, HF_ENDPOINT_URL, REDIS_URL, etc.

# 3. Run Redis (for crawl jobs)
docker run -p 6379:6379 redis:7

# 4. Start the API
uvicorn app.main:app --reload

# 5. Start a worker (separate terminal, for crawl jobs)
arq app.workers.crawl_worker.WorkerSettings
```

Or just `docker compose up` — this now brings up Redis, the API (`localhost:8000`),
the crawl worker, **and the frontend at `localhost:3000`**.

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

## License

MIT — see LICENSE.
