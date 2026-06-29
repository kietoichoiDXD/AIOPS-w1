from pydantic import BaseModel, Field
from app.models.enums import HealthStatus


class ServicesStatus(BaseModel):
    """Dependency health status."""

    s3_audit_bucket: str = Field(..., description="'connected' or 'disconnected'")
    bedrock_api: str = Field(..., description="'accessible' or 'inaccessible'")
    s3_cur_bucket: str = Field(..., description="'reachable' or 'unreachable'")

    model_config = {
        "json_schema_extra": {
            "example": {
                "s3_audit_bucket": "connected",
                "bedrock_api": "accessible",
                "s3_cur_bucket": "reachable",
            }
        }
    }


class HealthResponse(BaseModel):
    """Response body for GET /health."""

    status: HealthStatus = Field(..., description="Overall health: healthy / degraded / unhealthy")
    timestamp: str = Field(..., description="RFC3339 UTC timestamp of this check")
    services: ServicesStatus = Field(..., description="Per-dependency health detail")

    model_config = {
        "json_schema_extra": {
            "example": {
                "status": "healthy",
                "timestamp": "2026-06-26T10:00:00Z",
                "services": {
                    "s3_audit_bucket": "connected",
                    "bedrock_api": "accessible",
                    "s3_cur_bucket": "reachable",
                },
            }
        }
    }
