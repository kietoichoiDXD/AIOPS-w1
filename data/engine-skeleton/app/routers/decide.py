from fastapi import APIRouter, Header, HTTPException, Request, Response, status

from app.routers.detect import _validate_headers
from app.schemas.common import ErrorResponse
from app.schemas.decide import DecideRequest, DecideResponse

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



    locked = bool(tenant_state and tenant_state.is_locked(x_tenant_id, env))
    if locked:
        response.headers["X-Containment-Status"] = "LOCKED"
        response.headers["X-Lock-Reason"] = "error_budget_exceeded"

    decision_service = request.app.state.decision_service
    return decision_service.decide(payload, locked=locked)
