from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field, HttpUrl


class OutputFormat(str, Enum):
    markdown = "markdown"
    html = "html"
    text = "text"
    links = "links"


# ---------- Scrape ----------
class ScrapeRequest(BaseModel):
    url: HttpUrl
    formats: list[OutputFormat] = [OutputFormat.markdown]
    render_js: bool = False
    only_main_content: bool = True
    include_tags: Optional[list[str]] = None
    exclude_tags: Optional[list[str]] = None


class PageMetadata(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    language: Optional[str] = None
    status_code: Optional[int] = None
    source_url: str


class ScrapeResult(BaseModel):
    metadata: PageMetadata
    markdown: Optional[str] = None
    html: Optional[str] = None
    text: Optional[str] = None
    links: Optional[list[str]] = None


# ---------- Map ----------
class MapRequest(BaseModel):
    url: HttpUrl
    limit: int = Field(default=5000, le=50_000)
    include_subdomains: bool = False
    search: Optional[str] = None  # filter URLs containing this substring


class MapResult(BaseModel):
    base_url: str
    links: list[str]
    count: int


# ---------- Crawl ----------
class CrawlRequest(BaseModel):
    url: HttpUrl
    max_pages: int = Field(default=100, le=10_000)
    max_depth: int = Field(default=3, le=10)
    render_js: bool = False
    formats: list[OutputFormat] = [OutputFormat.markdown]
    include_paths: Optional[list[str]] = None  # regex patterns to include
    exclude_paths: Optional[list[str]] = None  # regex patterns to exclude
    allow_external: bool = False


class CrawlStatus(str, Enum):
    queued = "queued"
    running = "running"
    completed = "completed"
    failed = "failed"


class FailedPage(BaseModel):
    url: str
    error: str


class CrawlJob(BaseModel):
    id: str
    status: CrawlStatus
    total: int = 0
    completed: int = 0
    data: list[ScrapeResult] = []
    failed_pages: list[FailedPage] = []
    error: Optional[str] = None


# ---------- Extract ----------
class ExtractRequest(BaseModel):
    url: Optional[HttpUrl] = None
    content: Optional[str] = None  # supply raw text instead of a URL
    json_schema: dict[str, Any] = Field(alias="schema")
    prompt: Optional[str] = None  # extra instructions for the LLM
    render_js: bool = False

    model_config = {"populate_by_name": True}


class ExtractResult(BaseModel):
    data: dict[str, Any]
    source_url: Optional[str] = None
