from __future__ import annotations

from pydantic import BaseModel, Field
from app.models.enums import ActionExecutionStatus, ContainmentAction, DataSourceType, NextAction




class ActionExecuted(BaseModel):
    """Details of the containment action the CDO executed."""

    action: ContainmentAction
    target: str = Field(..., description="Resource ARN or ID that was acted upon")
    status: ActionExecutionStatus
    execution_time_seconds: int | None = Field(None, ge=0)


class PostTelemetryWindow(BaseModel):
    """Post-action telemetry — same structure as detect request (simplified)."""

    data_source_type: DataSourceType
    aws_cost_explorer_daily: list[dict] = Field(
        ..., description="CE rows observed after the containment action"
    )
    aws_cur_line_items: list[dict] | None = None
    s3_bucket_uri: str | None = None


class VerifyRequest(BaseModel):
    """Request body for POST /v1/verify."""

    correlation_id: str = Field(..., description="UUID v4 — must match across detect→decide→verify")
    idempotency_key: str = Field(
        ...,
        pattern=r"^[a-f0-9\-]{36}:[0-9]{4}-[0-9]{2}-[0-9]{2}:[a-z0-9\-]+$",
    )
    dry_run_mode: bool = Field(..., description="Must match dry_run_mode from /v1/decide")
    action_executed: ActionExecuted
    post_telemetry_window: PostTelemetryWindow

    model_config = {
        "json_schema_extra": {
            "example": {
                "correlation_id": "9b1deb4d-3b7d-4bad-9bdd-2b0d7b3dcb6d",
                "idempotency_key": "b2c3d4e5-f6a7-8901-bcde-f12345678901:2026-06-24:daily-batch",
                "dry_run_mode": True,
                "action_executed": {
                    "action": "tag-for-review",
                    "target": "i-0abcd1234efgh5678",
                    "status": "COMPLETED",
                    "execution_time_seconds": 3,
                },
                "post_telemetry_window": {
                    "data_source_type": "RAW_JSON",
                    "aws_cost_explorer_daily": [
                        {
                            "date": "2026-06-24",
                            "linked_account_id": "200000000012",
                            "linked_account_name": "squad-ml-research",
                            "service_code": "AmazonEC2",
                            "service": "Amazon Elastic Compute Cloud - Compute",
                            "region": "ap-southeast-1",
                            "unblended_cost": 0.0,
                            "cost_ratio_to_7d_avg": 0.0,
                            "day_of_week": 2,
                            "is_weekend": False,
                            "is_estimated": False,
                        }
                    ],
                    "aws_cur_line_items": [],
                },
            }
        }
    }




class EscalationMetrics(BaseModel):
    unblended_cost_24h_usd: float
    cost_ratio_to_7d_avg: float
    usage_density_24h: float


class EscalationBundle(BaseModel):
    """Context package for on-call engineer when next_action=ESCALATE."""

    reason: str = Field(..., description="Detailed reason why self-healing failed")
    logs: list[str] | None = Field(None, description="Raw system log lines")
    metrics: EscalationMetrics | None = None


class VerifyResponse(BaseModel):
    """Response body for POST /v1/verify."""

    success: bool = Field(..., description="True if cost metric returned to baseline")
    regression_detected: bool = Field(..., description="True if post-action cost spiked as side-effect")
    next_action: NextAction = Field(..., description="CDO next step: DONE/RETRY/ROLLBACK/ESCALATE")
    escalation_bundle: EscalationBundle | None = Field(
        None, description="Populated when next_action=ESCALATE"
    )

    model_config = {
        "json_schema_extra": {
            "example": {
                "success": True,
                "regression_detected": False,
                "next_action": "DONE",
            }
        }
    }
