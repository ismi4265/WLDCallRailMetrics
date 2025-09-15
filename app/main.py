# app/main.py
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .core.config import settings, ORIGINS
from .core.db import init_db, migrate_db

# Routers
from .routers.ingest import router as ingest_router
from .routers.metrics import router as metrics_router
from .routers.reports import router as reports_router
from .routers.admin import router as admin_router

# Optional webhooks router (ignored if missing/broken)
try:
    from .routers.webhooks import router as webhooks_router  # type: ignore
except Exception:
    webhooks_router = None

# Optional extra metrics
try:
    from .routers.metrics_extra import router as metrics_extra_router  # type: ignore
except Exception:
    metrics_extra_router = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    init_db()
    migrate_db()
    yield
    # Shutdown (no-op for now)


app = FastAPI(
    title="WLD CallRail Metrics",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=ORIGINS if isinstance(ORIGINS, list) else ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Health
@app.get("/health")
def health():
    return {"status": "ok"}


# Routers
app.include_router(ingest_router)
app.include_router(metrics_router)
app.include_router(reports_router)
app.include_router(admin_router)

if webhooks_router:
    app.include_router(webhooks_router)

if metrics_extra_router:
    app.include_router(metrics_extra_router)
