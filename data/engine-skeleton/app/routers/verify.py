from fastapi import APIRouter, Header, HTTPException, Request, status
from fastapi.responses import JSONResponse

from app.routers.detect import _validate_headers
from app.schemas.common import ErrorResponse
from app.schemas.verify import VerifyRequest, VerifyResponse
from app.services.ml.idempotency import (
    IdempotencyCacheHit,
    IdempotencyConflict,
    IdempotencyMismatch,
)

router = APIRouter(prefix="/v1", tags=["Verify"])


@router.post(
    "/verify",
    response_model=VerifyResponse,
    status_code=status.HTTP_200_OK,
    summary="Verify Containment Outcome",
    description=(
        "CDO submits post-action telemetry. "
        "AI Engine evaluates whether the cost anomaly resolved and returns "
        "next_action: DONE | RETRY | ROLLBACK | ESCALATE."
    ),
    responses={
        400: {"model": ErrorResponse, "description": "Schema validation error"},
        429: {"model": ErrorResponse, "description": "Rate limit exceeded (100 req/min/tenant)"},
    },
)
async def verify(
    payload: VerifyRequest,
    request: Request,
    x_tenant_id: str | None = Header(None, alias="X-Tenant-Id"),
    x_idempotency_key: str | None = Header(None, alias="X-Idempotency-Key"),
    x_payload_sha256: str | None = Header(None, alias="X-Payload-SHA256"),
    x_request_timestamp: str | None = Header(None, alias="X-Request-Timestamp"),
    x_dry_run_mode: str | None = Header(None, alias="X-Dry-Run-Mode"),
    x_correlation_id: str | None = Header(None, alias="X-Correlation-Id"),
) -> VerifyResponse:
    _validate_headers(
        x_tenant_id,
        x_idempotency_key,
        x_payload_sha256,
        x_request_timestamp,
        x_dry_run_mode,
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

    decision_service = request.app.state.decision_service
    result = decision_service.verify(payload)

    if idempotency and not dry_run:
        idempotency.mark_complete(x_idempotency_key, result.model_dump())

    return result
