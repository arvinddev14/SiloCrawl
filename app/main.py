import logging
import time
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse

from app.api.routes import router
from app.core.auth import require_api_key
from app.core.config import get_settings
from app.core.telemetry import setup_logging
from app.db import init_db
from app.db.metrics import collect_metrics

access_logger = logging.getLogger("silocrawl.access")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    setup_logging()
    await init_db()
    yield


app = FastAPI(
    title="SiloCrawl",
    version="0.1.0",
    description="Open-source, LLM-powered web scraping toolkit.",
    lifespan=lifespan,
)

_cors_origins = [
    o.strip() for o in get_settings().cors_allow_origins.split(",") if o.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)


@app.middleware("http")
async def access_log(request: Request, call_next):
    start = time.monotonic()
    response = await call_next(request)
    if request.url.path not in ("/health", "/metrics"):
        extra = {
            "method": request.method,
            "path": request.url.path,
            "status": response.status_code,
            "duration_ms": int((time.monotonic() - start) * 1000),
        }
        key_id = getattr(request.state, "api_key_id", None)
        if key_id:
            extra["api_key_id"] = key_id
        access_logger.info("request", extra=extra)
    return response


@app.get("/", include_in_schema=False)
async def root():
    """The bare URL shouldn't be a confusing 404 — send people to the docs."""
    return RedirectResponse("/docs")


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/metrics", dependencies=[Depends(require_api_key)])
async def metrics(hours: int = 24):
    """Aggregated run/LLM/crawl metrics from the durable store. hours=0 → all time."""
    return await collect_metrics(hours=hours)
