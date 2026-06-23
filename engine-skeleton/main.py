"""
FinOps Watch AI Engine - Entry Point
=====================================
Production-grade FastAPI application serving the FinOps anomaly detection engine.
Designed for ECS Fargate deployment (1 vCPU / 2048 MB as per Deployment Contract).

Run locally:  uvicorn main:app --host 0.0.0.0 --port 8080 --reload
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.router import api_router
from api.middleware.request_context import RequestContextMiddleware
from config.settings import get_settings

settings = get_settings()

# ---------------------------------------------------------------------------
# Structured logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=getattr(logging, settings.log_level),
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S%z",
)
logger = logging.getLogger("finops-engine")


# ---------------------------------------------------------------------------
# Lifespan (startup / shutdown hooks)
# ---------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info(
        "FinOps Watch AI Engine starting | env=%s | version=%s",
        settings.environment,
        settings.app_version,
    )
    # Future: init DB connections, load ML models, warm caches here
    yield
    logger.info("FinOps Watch AI Engine shutting down gracefully")


# ---------------------------------------------------------------------------
# Application factory
# ---------------------------------------------------------------------------
app = FastAPI(
    title="FinOps Watch AI Engine",
    description=(
        "Continuous AWS cost anomaly detection and safe containment engine. "
        "TF2 Capstone Phase 2 — AIOps team."
    ),
    version=settings.app_version,
    lifespan=lifespan,
    docs_url="/docs" if settings.environment != "production" else None,
    redoc_url="/redoc" if settings.environment != "production" else None,
)

# ---------------------------------------------------------------------------
# Middleware
# ---------------------------------------------------------------------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_methods=["POST", "GET"],
    allow_headers=["*"],
)
app.add_middleware(RequestContextMiddleware)

# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
app.include_router(api_router)
