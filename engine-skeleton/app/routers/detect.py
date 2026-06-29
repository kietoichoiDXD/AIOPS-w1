import json
import re
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Header, HTTPException, Request, status
from fastapi.responses import JSONResponse

from app.config.settings import settings
from app.schemas.detect import DetectRequest, DetectResponse
from app.schemas.common import ErrorResponse
from app.services.ml.idempotency import (
    IdempotencyConflict,
    IdempotencyCacheHit,
    IdempotencyMismatch,
)

router = APIRouter(prefix="/v1", tags=["Detect"])



_TENANT_ID_PATTERN = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)


def _validate_headers(
    x_tenant_id: str | None,
    x_idempotency_key: str | None,
    x_payload_sha256: str | None,
    x_request_timestamp: str | None,
    x_dry_run_mode: str | None,
) -> None:
    missing = [
        name
        for name, val in [
            ("X-Tenant-Id", x_tenant_id),
            ("X-Idempotency-Key", x_idempotency_key),
            ("X-Payload-SHA256", x_payload_sha256),
            ("X-Request-Timestamp", x_request_timestamp),
            ("X-Dry-Run-Mode", x_dry_run_mode),
        ]
        if not val
    ]
    if missing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "success": False,
                "error_code": "ERR_INVALID_SCHEMA",
                "error_message": f"Missing required headers: {', '.join(missing)}",
            },
        )



    if not _TENANT_ID_PATTERN.match(x_tenant_id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "success": False,
                "error_code": "ERR_INVALID_SCHEMA",
                "error_message": (
                    "X-Tenant-Id must be a UUID (8-4-4-4-12 hex), "
                    f"got '{x_tenant_id}'"
                ),
            },
        )


    try:
        req_ts = datetime.fromisoformat(x_request_timestamp.replace("Z", "+00:00"))
        now = datetime.now(timezone.utc)
        skew = abs((now - req_ts).total_seconds())
        if skew > settings.clock_skew_tolerance_seconds:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "success": False,
                    "error_code": "ERR_REPLAY_DETECTED",
                    "error_message": (
                        f"X-Request-Timestamp skew {skew:.0f}s exceeds "
                        f"tolerance of {settings.clock_skew_tolerance_seconds}s. Sync NTP and retry."
                    ),
                },
            )
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "success": False,
                "error_code": "ERR_INVALID_SCHEMA",
                "error_message": "X-Request-Timestamp must be RFC3339 UTC format (e.g. 2026-06-26T10:00:00Z)",
            },
        )

    if x_dry_run_mode not in ("true", "false"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "success": False,
                "error_code": "ERR_INVALID_SCHEMA",
                "error_message": "X-Dry-Run-Mode must be 'true' or 'false'",
            },
        )


@router.post(
    "/detect",
    response_model=DetectResponse,
    status_code=status.HTTP_200_OK,
    summary="Detect Cost Anomalies",
    description=(
        "Accepts CUR + CE telemetry, runs the anomaly detection engine, "
        "and returns a list of detected anomalies synchronously. "
        "Requires X-Tenant-Id, X-Idempotency-Key, X-Payload-SHA256, "
        "X-Request-Timestamp, and X-Dry-Run-Mode headers."
    ),
    responses={
        400: {"model": ErrorResponse, "description": "Validation error or replay attack"},
        429: {"model": ErrorResponse, "description": "Rate limit exceeded"},
        500: {"model": ErrorResponse, "description": "Internal server error"},
    },
)
async def detect(
    payload: DetectRequest,
    request: Request,
    x_tenant_id: str | None = Header(None, alias="X-Tenant-Id"),
    x_idempotency_key: str | None = Header(None, alias="X-Idempotency-Key"),
    x_payload_sha256: str | None = Header(None, alias="X-Payload-SHA256"),
    x_request_timestamp: str | None = Header(None, alias="X-Request-Timestamp"),
    x_dry_run_mode: str | None = Header(None, alias="X-Dry-Run-Mode"),
    x_correlation_id: str | None = Header(None, alias="X-Correlation-Id"),
) -> DetectResponse:
    _validate_headers(
        x_tenant_id,
        x_idempotency_key,
        x_payload_sha256,
        x_request_timestamp,
        x_dry_run_mode,
    )

    correlation_id = x_correlation_id or str(uuid.uuid4())




    body_bytes = payload.model_dump_json().encode()
    idempotency = getattr(request.app.state, "idempotency", None)
    dry_run = x_dry_run_mode == "true"

    if idempotency and not payload.is_ad_hoc and not dry_run:
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

    detect_service = request.app.state.detect_service
    result = detect_service.detect(payload, correlation_id)



    tenant_state = getattr(request.app.state, "tenant_state", None)
    if tenant_state:
        for anomaly in result.anomalies_list:
            tenant_state.register_anomaly(
                anomaly.anomaly_id, x_tenant_id, anomaly.environment
            )


    if idempotency and not payload.is_ad_hoc and not dry_run:
        idempotency.mark_complete(x_idempotency_key, result.model_dump())

    return result
