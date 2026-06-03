from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # LLM
    hf_api_key: str = ""
    hf_endpoint_url: str = "https://api-inference.huggingface.co/models/openai/gpt-oss-120b/v1/"
    extract_model: str = "openai/gpt-oss-120b"
    extract_max_tokens: int = 4096

    # Queue
    redis_url: str = "redis://localhost:6379"

    # Fetcher
    user_agent: str = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
    request_timeout: float = 30.0
    max_retries: int = 3
    respect_robots: bool = True

    # Crawl limits (safety defaults)
    crawl_max_pages: int = 100
    crawl_max_depth: int = 3
    crawl_concurrency: int = 5

    # Content limits passed to the LLM (chars)
    extract_content_limit: int = 100_000


@lru_cache
def get_settings() -> Settings:
    return Settings()
