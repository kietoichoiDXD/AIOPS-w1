import re

from fastapi import APIRouter, Header, HTTPException, Path, Request, Response, status

from app.schemas.common import ErrorResponse
from app.schemas.status import RemediationStatusResponse, RollbackRequest, RollbackResponse

router = APIRouter(prefix="/v1", tags=["Status"])

_ANM_PATTERN = re.compile(r"^ANM-\d{4}-\d{4}[A-Z]$")


@router.get(
    "/status/{anomaly_id}",
    response_model=RemediationStatusResponse,
    summary="Get Remediation Status",
    description=(
        "Poll the current remediation status for a specific anomaly_id. "
        "If the tenant is in LOCKED_MODE, response headers will include "
        "X-Containment-Status: LOCKED."
    ),
    responses={
        403: {"model": ErrorResponse, "description": "Anomaly belongs to a different tenant"},
        404: {"model": ErrorResponse, "description": "Anomaly ID not found"},
        429: {"model": ErrorResponse, "description": "Rate limit exceeded (100 req/min/tenant)"},
    },
)
async def get_status(
    response: Response,
    request: Request,
    anomaly_id: str = Path(..., description="Anomaly ID in format ANM-YYYY-MMDD{A-Z}"),
    x_tenant_id: str | None = Header(None, alias="X-Tenant-Id"),
) -> RemediationStatusResponse:
    if not _ANM_PATTERN.match(anomaly_id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "success": False,
                "error_code": "ERR_INVALID_SCHEMA",
                "error_message": f"anomaly_id '{anomaly_id}' does not match format ANM-YYYY-MMDD{{A-Z}}",
            },
        )

    tenant_state = getattr(request.app.state, "tenant_state", None)


    if tenant_state and tenant_state.is_cross_tenant(anomaly_id, x_tenant_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "success": False,
                "error_code": "ERR_CROSS_TENANT_DENIED",
                "error_message": (
                    f"Anomaly '{anomaly_id}' does not belong to tenant '{x_tenant_id}'."
                ),
            },
        )

    detect_service = request.app.state.detect_service
    record = detect_service.get_status(anomaly_id)

    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "success": False,
                "error_code": "ERR_ANOMALY_NOT_FOUND",
                "error_message": f"No record found for anomaly_id={anomaly_id}",
            },
        )



    if tenant_state:
        owner = tenant_state.owner_of(anomaly_id) or x_tenant_id
        env = tenant_state.env_of(anomaly_id)
        record = record.model_copy(
            update={
                "containment_locked": tenant_state.is_locked(owner, env),
                "error_budget_remaining_pct": tenant_state.remaining_pct(owner, env),
            }
        )

    if record.containment_locked:
        response.headers["X-Containment-Status"] = "LOCKED"
        response.headers["X-Lock-Reason"] = "error_budget_exceeded"

    return record


@router.post(
    "/audit/{audit_id}/rollback",
    response_model=RollbackResponse,
    summary="Record Manual Rollback (False Positive)",
    description=(
        "CDO notifies the AI Engine that a remediation was manually rolled back "
        "(e.g. false positive). Updates the false-positive counter for model feedback "
        "and recalculates the error budget."
    ),
    responses={
        404: {"model": ErrorResponse, "description": "Audit ID not found"},
    },
)
async def record_rollback(
    payload: RollbackRequest,
    request: Request,
    audit_id: str = Path(..., description="Anomaly/Audit ID in format ANM-YYYY-MMDD{A-Z}"),
    x_tenant_id: str | None = Header(None, alias="X-Tenant-Id"),
) -> RollbackResponse:
    if not _ANM_PATTERN.match(audit_id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "success": False,
                "error_code": "ERR_INVALID_SCHEMA",
                "error_message": f"audit_id '{audit_id}' does not match format ANM-YYYY-MMDD{{A-Z}}",
            },
        )

    tenant_state = getattr(request.app.state, "tenant_state", None)
    if tenant_state and x_tenant_id and tenant_state.is_cross_tenant(audit_id, x_tenant_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "success": False,
                "error_code": "ERR_CROSS_TENANT_DENIED",
                "error_message": (
                    f"Anomaly '{audit_id}' does not belong to tenant '{x_tenant_id}'."
                ),
            },
        )

    decision_service = request.app.state.decision_service
    return decision_service.record_rollback(audit_id, payload, tenant_id=x_tenant_id or "default")
