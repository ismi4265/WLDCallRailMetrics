# app/main.py
from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .core.config import settings
from .core.db import init_db, migrate_db
from .routers.metrics import router as metrics_router
from .routers.reports import router as reports_router
from .routers.admin import router as admin_router

app = FastAPI(title="WLD CallRail Metrics API")

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if settings.CORS_ORIGINS == "*" else settings.CORS_ORIGINS.split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.on_event("startup")
def _startup():
    init_db()
    migrate_db()

@app.get("/health")
def health():
    return {"status": "ok"}

# Routers
app.include_router(metrics_router)
app.include_router(reports_router)
app.include_router(admin_router)
