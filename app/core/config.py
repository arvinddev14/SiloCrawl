from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # LLM
    hf_api_key: str = ""
    hf_endpoint_url: str = "https://api-inference.huggingface.co/models/openai/gpt-oss-120b/v1/"
    extract_model: str = "openai/gpt-oss-120b"
    extract_max_tokens: int = 4096

    # Model Router (SiloLoop): path to the agent->model config. Optional — when the
    # file is absent, the router falls back to the HF gpt-oss defaults above.
    models_config_path: str = "models.yaml"
    # Autonomous optimization (INC-B14): apply experiment-promoted models to live
    # routing. Off by default — promotions are recorded but change nothing.
    apply_model_promotions: bool = False

    # Queue
    redis_url: str = "redis://localhost:6379"

    # Durable store (system of record for SiloLoop)
    database_url: str = "sqlite+aiosqlite:///./silocrawl.db"

    # Observability
    telemetry_enabled: bool = True
    log_level: str = "INFO"

    # Auth (off by default — self-hosting stays zero-config)
    auth_enabled: bool = False
    api_keys: str = ""  # comma-separated accepted keys
    rate_limit_per_minute: int = 60  # per key; 0 = no rate limit

    # Fetcher
    user_agent: str = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
    request_timeout: float = 30.0
    max_retries: int = 3
    respect_robots: bool = True
    robots_cache_ttl: int = 3600  # seconds to cache a domain's robots.txt
    per_domain_delay: float = 1.0  # min seconds between requests to the same domain

    # Response cache (0 = disabled; freshness is the sane default for a scraper)
    scrape_cache_ttl: int = 0

    # Crawl limits (safety defaults)
    crawl_max_pages: int = 100
    crawl_max_depth: int = 3
    crawl_concurrency: int = 5

    # Documents (/v1/document)
    document_max_bytes: int = 25_000_000  # reject larger downloads/uploads

    # Content limits passed to the LLM (chars)
    extract_content_limit: int = 100_000
    # Deep extraction (loop path): map-reduce over long pages instead of truncating
    extract_max_chunks: int = 8  # cap on chunks mapped per page (cost bound)
    extract_chunk_concurrency: int = 3  # parallel chunk extractions


@lru_cache
def get_settings() -> Settings:
    return Settings()
