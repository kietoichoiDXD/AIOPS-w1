import datetime

from fastapi import APIRouter

from app.config.settings import settings
from app.models.enums import HealthStatus
from app.schemas.health import HealthResponse, ServicesStatus

router = APIRouter(tags=["Health"])


@router.get(
    "/health",
    response_model=HealthResponse,
    summary="Health Check",
    description=(
        "Called by ALB and ECS Fargate every 30 seconds. "
        "No authentication required. "
        "Returns overall status and dependency health."
    ),
)
def health_check() -> HealthResponse:
    services = ServicesStatus(
        s3_audit_bucket=settings.mock_s3_audit_status,
        bedrock_api=settings.mock_bedrock_status,
        s3_cur_bucket=settings.mock_s3_cur_status,
    )

    if "disconnected" in (services.s3_audit_bucket, services.s3_cur_bucket):
        overall = HealthStatus.degraded
    elif services.bedrock_api == "inaccessible":
        overall = HealthStatus.degraded
    else:
        overall = HealthStatus.healthy

    return HealthResponse(
        status=overall,
        timestamp=datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        services=services,
    )
