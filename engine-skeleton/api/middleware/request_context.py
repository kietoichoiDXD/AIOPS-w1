"""
Request context middleware.
Extracts X-Tenant-Id and X-Correlation-Id from headers,
validates them, and stores in request state for downstream use.
"""

import uuid
import logging
import time

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

logger = logging.getLogger("finops-engine.middleware")


class RequestContextMiddleware(BaseHTTPMiddleware):
    """
    Cross-cutting concerns for every request:
    1. Extract & validate tenant_id
    2. Generate correlation_id if missing
    3. Log request timing
    """

    # Paths that don't require tenant_id
    EXEMPT_PATHS = {"/health", "/docs", "/redoc", "/openapi.json"}

    async def dispatch(self, request: Request, call_next):
        start_time = time.monotonic()

        # --- Skip auth for health & docs ---
        if request.url.path in self.EXEMPT_PATHS:
            response = await call_next(request)
            return response

        # --- Tenant extraction ---
        tenant_id = request.headers.get("x-tenant-id", "").strip()
        if not tenant_id:
            return JSONResponse(
                status_code=400,
                content={
                    "error": "missing_tenant_id",
                    "detail": "X-Tenant-Id header is required for all API calls",
                },
            )

        # --- Correlation ID ---
        correlation_id = request.headers.get("x-correlation-id", "").strip()
        if not correlation_id:
            correlation_id = str(uuid.uuid4())

        # --- Store in request state ---
        request.state.tenant_id = tenant_id
        request.state.correlation_id = correlation_id

        # --- Execute request ---
        response = await call_next(request)

        # --- Add response headers ---
        response.headers["X-Correlation-Id"] = correlation_id
        response.headers["X-Tenant-Id"] = tenant_id

        # --- Log request ---
        elapsed_ms = (time.monotonic() - start_time) * 1000
        logger.info(
            "request_completed | tenant=%s | correlation=%s | method=%s | path=%s | status=%s | latency_ms=%.1f",
            tenant_id,
            correlation_id,
            request.method,
            request.url.path,
            response.status_code,
            elapsed_ms,
        )

        return response
