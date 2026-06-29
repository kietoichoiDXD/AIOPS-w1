"""
FinOps Watch — AI Engine (Production)
======================================
FastAPI application entry point.

Endpoints:
  GET  /health                         — ALB / ECS health check
  POST /v1/detect                      — Cost anomaly detection (statistical + optional XGBoost)
  POST /v1/decide                      — Containment action planning + RCA
  POST /v1/verify                      — Post-action verification
  GET  /v1/status/{anomaly_id}         — Remediation status poll
  POST /v1/audit/{audit_id}/rollback   — Manual rollback (false-positive feedback)

Contract: contracts/ai-api-contract.md v1.5.0

Detection engine: StatisticalDetectService
  - 5 per-mechanism detectors (sudden_spike, gradual_drift, idle_resource,
    runaway_usage, untagged_spend) operating purely on CUR cost behaviour.
  - No synthetic CPU/memory data required (per REVIEW_v2_detect_anomaly.md §2.1).
  - Optional XGBoost overlay (weight 0.30) when model available via DATA_DIR or
    MLFLOW_TRACKING_URI env vars.

Idempotency: DynamoDB conditional write (DYNAMODB_TABLE env) or in-process dict.
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.config.settings import settings
from app.routers import detect, decide, verify, status as status_router, health
from app.services.ml.statistical_detect_service import StatisticalDetectService
from app.services.ml.decision_service import ProductionDecisionService
from app.services.ml.idempotency import IdempotencyService
from app.services.ml.tenant_state import TenantStateService
from app.services.rate_limiter import RateLimiter


@asynccontextmanager
async def lifespan(app: FastAPI):
    tenant_state = TenantStateService()
    detect_svc   = StatisticalDetectService()
    decision_svc = ProductionDecisionService(
        detect_service=detect_svc, tenant_state=tenant_state
    )
    idempotency  = IdempotencyService()
    rate_limiter = RateLimiter(settings.rate_limit_per_min)

    app.state.tenant_state     = tenant_state
    app.state.detect_service   = detect_svc
    app.state.decision_service = decision_svc
    app.state.idempotency      = idempotency
    app.state.rate_limiter     = rate_limiter
    yield


app = FastAPI(
    title="FinOps Watch — AI Engine",
    description=(
        "Production AI Engine for TF2 FinOps Watch. "
        "Detects AWS cost anomalies via per-mechanism statistical detectors, "
        "plans containment actions, and verifies remediation outcomes. "
        "Contract: ai-api-contract.md v1.5.0."
    ),
    version=settings.app_version,
    contact={
        "name": "TF2 FinOps Watch — AI Team",
        "email": "trankanjin803@gmail.com",
    },
    license_info={"name": "Internal — TF2 Capstone Phase 2"},
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
)



@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
    """Per-tenant rate limit (contract §3) → 429 ERR_RATE_LIMITED on /v1/* paths."""
    if request.url.path.startswith("/v1/"):
        limiter = getattr(request.app.state, "rate_limiter", None)
        tenant = request.headers.get("X-Tenant-Id")
        if limiter and tenant:
            allowed, retry_after = limiter.allow(tenant)
            if not allowed:
                return JSONResponse(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    content={
                        "success": False,
                        "error_code": "ERR_RATE_LIMITED",
                        "error_message": (
                            f"Tenant '{tenant}' exceeded {limiter.max_per_min} requests/min. "
                            "Back off and retry (1s→2s→4s→8s→16s)."
                        ),
                    },
                    headers={"Retry-After": str(retry_after)},
                )
    return await call_next(request)




app.include_router(health.router)
app.include_router(detect.router)
app.include_router(decide.router)
app.include_router(verify.router)
app.include_router(status_router.router)




@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    """Unwrap dict detail so error_code appears at the top level of the response."""
    if isinstance(exc.detail, dict):
        return JSONResponse(status_code=exc.status_code, content=exc.detail)
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "success": False,
            "error_code": "ERR_HTTP",
            "error_message": str(exc.detail),
        },
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    errors = exc.errors()
    first = errors[0] if errors else {}
    field = " → ".join(str(loc) for loc in first.get("loc", ["unknown"]))
    return JSONResponse(
        status_code=status.HTTP_400_BAD_REQUEST,
        content={
            "success": False,
            "error_code": "ERR_INVALID_SCHEMA",
            "error_message": f"Validation failed on field '{field}': {first.get('msg', 'invalid value')}",
        },
    )


@app.exception_handler(Exception)
async def generic_exception_handler(request: Request, exc: Exception):
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "success": False,
            "error_code": "ERR_INTERNAL",
            "error_message": "An unexpected error occurred. Check server logs.",
        },
    )
