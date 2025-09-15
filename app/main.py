from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .core.config import settings, ORIGINS
from .core.db import init_db, migrate_db

# Existing routers
from .routers.ingest import router as ingest_router
from .routers.metrics import router as metrics_router
from .routers.reports import router as reports_router
from .routers.admin import router as admin_router

# Optional: if you still keep webhooks
try:
    from .routers.webhooks import router as webhooks_router
except Exception:
    webhooks_router = None

# New extra metrics
from .routers.metrics_extra import router as metrics_extra_router


app = FastAPI(
    title="WLD CallRail Metrics",
    version="1.0.0",
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=ORIGINS if isinstance(ORIGINS, list) else ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Startup
@app.on_event("startup")
def on_startup():
    init_db()
    migrate_db()


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

# Include the new metrics-extra endpoints
app.include_router(metrics_extra_router)
