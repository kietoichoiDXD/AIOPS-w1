from fastapi import APIRouter, Header, HTTPException, Request, status

from app.routers.detect import _validate_headers
from app.schemas.common import ErrorResponse
from app.schemas.verify import VerifyRequest, VerifyResponse

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

    decision_service = request.app.state.decision_service
    return decision_service.verify(payload)
