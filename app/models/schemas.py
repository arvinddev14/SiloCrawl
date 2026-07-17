from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field, HttpUrl


class OutputFormat(str, Enum):
    markdown = "markdown"
    html = "html"
    text = "text"
    links = "links"
    screenshot = "screenshot"  # base64 PNG; forces headless-browser rendering


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
    screenshot: Optional[str] = None  # base64-encoded full-page PNG


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
    # Optional since INC-B5: omit for freeform "key facts" extraction guided by prompt.
    json_schema: Optional[dict[str, Any]] = Field(default=None, alias="schema")
    prompt: Optional[str] = None  # extra instructions for the LLM
    render_js: bool = False

    model_config = {"populate_by_name": True}


# ---------- Client events (UX telemetry, INC-B11) ----------
class ClientEvent(BaseModel):
    name: str = Field(min_length=1, max_length=100)  # e.g. "playground.wait"
    value: Optional[float] = None  # e.g. wait duration in ms
    meta: Optional[dict[str, Any]] = None


class ClientEventBatch(BaseModel):
    events: list[ClientEvent] = Field(min_length=1, max_length=50)


# ---------- Document ----------
class DocumentRequest(BaseModel):
    url: HttpUrl
    # Same optional extraction knobs as /v1/extract; omit both to just convert.
    json_schema: Optional[dict[str, Any]] = Field(default=None, alias="schema")
    prompt: Optional[str] = None

    model_config = {"populate_by_name": True}


class DocumentResult(BaseModel):
    text: str  # the document converted to text/markdown
    metadata: dict[str, Any]  # format, size_bytes, pages/sheets/slides, source
    # Present only when a schema/prompt was supplied (mirrors ExtractResult).
    data: Optional[dict[str, Any]] = None
    confidence: Optional[float] = None
    verification: Optional[dict[str, Any]] = None
    repair: Optional[dict[str, Any]] = None


class ExtractResult(BaseModel):
    data: dict[str, Any]
    source_url: Optional[str] = None
    # Populated only when the caller opts in with verify=true (INC-B3).
    confidence: Optional[float] = None  # 0..1 combined trust score
    verification: Optional[dict[str, Any]] = None  # full VerificationReport dump
    # Populated only when the caller opts in with repair=true (INC-B4).
    repair: Optional[dict[str, Any]] = None  # attempted/problems/repaired_fields/...
    # Populated only on the deep (loop) extraction path (INC-B5).
    extraction: Optional[dict[str, Any]] = None  # chunks/llm_calls/retried_fields/...
