from fastapi import APIRouter, Header, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse

from app.routers.detect import _validate_headers
from app.schemas.common import ErrorResponse
from app.schemas.decide import DecideRequest, DecideResponse
from app.services.ml.idempotency import (
    IdempotencyCacheHit,
    IdempotencyConflict,
    IdempotencyMismatch,
)

router = APIRouter(prefix="/v1", tags=["Decide"])


@router.post(
    "/decide",
    response_model=DecideResponse,
    status_code=status.HTTP_200_OK,
    summary="Plan Containment Action",
    description=(
        "Accepts an anomaly context from /v1/detect, runs root cause analysis, "
        "and returns a containment action plan with AWS CLI payloads and dashboard data. "
        "X-Correlation-Id must match the correlation_id returned by /v1/detect."
    ),
    responses={
        400: {"model": ErrorResponse, "description": "Schema validation error"},
        403: {"model": ErrorResponse, "description": "Anomaly belongs to a different tenant"},
        404: {"model": ErrorResponse, "description": "Anomaly ID not found"},
        429: {"model": ErrorResponse, "description": "Rate limit exceeded (100 req/min/tenant)"},
    },
)
async def decide(
    payload: DecideRequest,
    request: Request,
    response: Response,
    x_tenant_id: str | None = Header(None, alias="X-Tenant-Id"),
    x_idempotency_key: str | None = Header(None, alias="X-Idempotency-Key"),
    x_payload_sha256: str | None = Header(None, alias="X-Payload-SHA256"),
    x_request_timestamp: str | None = Header(None, alias="X-Request-Timestamp"),
    x_dry_run_mode: str | None = Header(None, alias="X-Dry-Run-Mode"),
    x_correlation_id: str | None = Header(None, alias="X-Correlation-Id"),
) -> DecideResponse:
    _validate_headers(
        x_tenant_id,
        x_idempotency_key,
        x_payload_sha256,
        x_request_timestamp,
        x_dry_run_mode,
    )

    anomaly_id = payload.anomaly_context.anomaly_id
    env = payload.anomaly_context.environment.value
    tenant_state = getattr(request.app.state, "tenant_state", None)

    if tenant_state and tenant_state.is_cross_tenant(anomaly_id, x_tenant_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "success": False,
                "error_code": "ERR_CROSS_TENANT_DENIED",
                "error_message": (
                    f"Anomaly '{anomaly_id}' does not belong to tenant "
                    f"'{x_tenant_id}'. Cross-tenant containment is denied."
                ),
            },
        )

    body_bytes = payload.model_dump_json().encode()
    idempotency = getattr(request.app.state, "idempotency", None)
    dry_run = x_dry_run_mode == "true"

    if idempotency and not dry_run:
        try:
            idempotency.check_and_set(x_idempotency_key, body_bytes)
        except IdempotencyCacheHit as hit:
            return JSONResponse(status_code=200, content=hit.response_body)
        except IdempotencyConflict:
            raise HTTPException(
                status_code=409,
                detail={
                    "success": False,
                    "error_code": "ERR_IDEMPOTENCY_IN_PROGRESS",
                    "error_message": (
                        f"Request with idempotency key '{x_idempotency_key}' is already "
                        "being processed. Retry after the current request completes."
                    ),
                },
            )
        except IdempotencyMismatch:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "success": False,
                    "error_code": "ERR_IDEMPOTENCY_MISMATCH",
                    "error_message": (
                        f"Idempotency key '{x_idempotency_key}' was already used with "
                        "a different payload. Use a new key for a different request."
                    ),
                },
            )

    locked = bool(tenant_state and tenant_state.is_locked(x_tenant_id, env))
    if locked:
        response.headers["X-Containment-Status"] = "LOCKED"
        response.headers["X-Lock-Reason"] = "error_budget_exceeded"

    decision_service = request.app.state.decision_service
    result = decision_service.decide(payload, locked=locked)

    if idempotency and not dry_run:
        idempotency.mark_complete(x_idempotency_key, result.model_dump())

    return result
