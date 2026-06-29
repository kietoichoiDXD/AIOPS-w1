from __future__ import annotations

from pydantic import BaseModel, Field
from app.models.enums import (
    AnomalyType,
    AppliedActionType,
    ContainmentAction,
    Environment,
    RollbackActionType,
)




class AnomalyContext(BaseModel):
    """Anomaly context forwarded from /v1/detect response."""

    anomaly_id: str = Field(..., description="ID from detect response anomalies_list")
    anomaly_type: AnomalyType
    resource_id: str = Field(..., description="AWS resource ARN or logical ID")
    environment: Environment
    unblended_cost_24h_usd: float = Field(..., ge=0)
    cost_ratio_to_7d_avg: float = Field(..., ge=0)
    responsible_team: str | None = Field(None)
    cost_center_code: str | None = Field(None)

    model_config = {
        "json_schema_extra": {
            "example": {
                "anomaly_id": "ANM-2026-0626A",
                "anomaly_type": "runaway_usage",
                "resource_id": "i-0abcd1234efgh5678",
                "environment": "ml-research",
                "unblended_cost_24h_usd": 427.50,
                "cost_ratio_to_7d_avg": 18.2,
                "responsible_team": "squad-ml-core",
                "cost_center_code": "CC-9001",
            }
        }
    }


class DecideRequest(BaseModel):
    """Request body for POST /v1/decide."""

    correlation_id: str = Field(..., description="UUID v4 — must match correlation_id from /v1/detect")
    idempotency_key: str = Field(
        ...,
        pattern=r"^[a-f0-9\-]{36}:[0-9]{4}-[0-9]{2}-[0-9]{2}:[a-z0-9\-]+$",
        description="Format: {tenant_uuid}:{billing_period_date}:{batch_type}",
    )
    dry_run_mode: bool = Field(..., description="True = generate plan only, do not execute")
    anomaly_context: AnomalyContext

    model_config = {
        "json_schema_extra": {
            "example": {
                "correlation_id": "9b1deb4d-3b7d-4bad-9bdd-2b0d7b3dcb6d",
                "idempotency_key": "a1b2c3d4-e5f6-7890-abcd-ef1234567890:2026-06-23:daily-batch",
                "dry_run_mode": True,
                "anomaly_context": {
                    "anomaly_id": "ANM-2026-0626A",
                    "anomaly_type": "runaway_usage",
                    "resource_id": "i-0abcd1234efgh5678",
                    "environment": "ml-research",
                    "unblended_cost_24h_usd": 427.50,
                    "cost_ratio_to_7d_avg": 18.2,
                    "responsible_team": "squad-ml-core",
                    "cost_center_code": "CC-9001",
                },
            }
        }
    }




class ActionPlanStep(BaseModel):
    step: int = Field(..., ge=1, description="Sequential step number (starts at 1)")
    action: ContainmentAction
    target: str = Field(..., description="Resource ARN or ID this step targets")
    params: dict = Field(default_factory=dict, description="Optional step parameters")


class AppliedPayload(BaseModel):
    """AWS CLI command to execute the containment action."""

    action_type: AppliedActionType
    aws_cli_command: str = Field(..., description="Complete AWS CLI command for CDO to run")


class RollbackPayload(BaseModel):
    """AWS CLI command to undo the containment action."""

    action_type: RollbackActionType
    aws_cli_rollback_command: str = Field(..., description="Complete AWS CLI rollback command")
    original_resource_id: str = Field(..., description="Original resource ARN — verify rollback target")


class FinanceMetrics(BaseModel):
    unblended_cost_24h_usd: float
    cost_ratio_to_7d_avg: float
    projected_monthly_waste_usd: float


class FinanceAllocation(BaseModel):
    responsible_team: str
    cost_center_code: str


class FinanceDashboardData(BaseModel):
    """Payload for Finance Dashboard / CFO — no technical detail."""

    target_recipient: str = Field(..., description="Audience label")
    metrics: FinanceMetrics
    allocation: FinanceAllocation
    executive_summary: str = Field(..., description="Plain-language summary for executives")


class TechnicalContext(BaseModel):
    aws_service: str
    usage_type: str
    pricing_unit: str
    usage_amount_24h: float
    usage_density_24h: float


class RootCauseAnalysis(BaseModel):
    primary_driver_feature: str
    technical_reason: str
    missing_mandatory_tags: list[str] = Field(default_factory=list)


class SlackRouting(BaseModel):
    channel_name: str
    webhook_url_pointer: str | None = None


class EngineeringDashboardData(BaseModel):
    """Payload for Engineering Console & Slack alert."""

    target_recipient: str
    technical_context: TechnicalContext
    root_cause_analysis: RootCauseAnalysis
    slack_routing: SlackRouting


class DecideResponse(BaseModel):
    """Response body for POST /v1/decide."""

    matched_runbook: str = Field(..., description="Runbook name matched from library")
    action_plan: list[ActionPlanStep] = Field(..., description="Ordered list of containment steps")
    applied_payload: AppliedPayload
    rollback_payload: RollbackPayload
    finance_dashboard_data: FinanceDashboardData
    engineering_dashboard_data: EngineeringDashboardData
    correlation_id: str = Field(..., description="UUID v4 — carry forward to /v1/verify")
    dry_run_mode: bool = Field(..., description="Echo of dry_run_mode from request")

    model_config = {
        "json_schema_extra": {
            "example": {
                "matched_runbook": "RunawayMLClusterContainmentRunbook",
                "action_plan": [
                    {"step": 1, "action": "tag-for-review", "target": "i-0abcd1234efgh5678", "params": {}},
                    {
                        "step": 2,
                        "action": "time-gated-countdown",
                        "target": "i-0abcd1234efgh5678",
                        "params": {"time_lock_seconds": 14400, "fallback_action": "auto-shutdown"},
                    },
                ],
                "applied_payload": {
                    "action_type": "inject_aws_tag",
                    "aws_cli_command": (
                        "aws ec2 create-tags --resources i-0abcd1234efgh5678 "
                        "--tags Key=finops:review,Value=pending Key=finops:anomaly-id,Value=ANM-2026-0626A "
                        "--region ap-southeast-1"
                    ),
                },
                "rollback_payload": {
                    "action_type": "remove_aws_tag",
                    "aws_cli_rollback_command": (
                        "aws ec2 delete-tags --resources i-0abcd1234efgh5678 "
                        "--tags Key=finops:review Key=finops:anomaly-id --region ap-southeast-1"
                    ),
                    "original_resource_id": "i-0abcd1234efgh5678",
                },
                "finance_dashboard_data": {
                    "target_recipient": "Finance Team & CFO Dashboard",
                    "metrics": {
                        "unblended_cost_24h_usd": 427.50,
                        "cost_ratio_to_7d_avg": 18.2,
                        "projected_monthly_waste_usd": 12825.00,
                    },
                    "allocation": {"responsible_team": "squad-ml-core", "cost_center_code": "CC-9001"},
                    "executive_summary": "GPU instance running idle for 3 days — $427/day waste detected.",
                },
                "engineering_dashboard_data": {
                    "target_recipient": "Engineering Console & Slack #finops-alert-engineering",
                    "technical_context": {
                        "aws_service": "AmazonEC2",
                        "usage_type": "BoxUsage:g4dn.xlarge",
                        "pricing_unit": "Hrs",
                        "usage_amount_24h": 24.0,
                        "usage_density_24h": 1.0,
                    },
                    "root_cause_analysis": {
                        "primary_driver_feature": "usage_density_24h",
                        "technical_reason": "EC2 g4dn.xlarge running 100% of 24h with no scheduled training jobs.",
                        "missing_mandatory_tags": [],
                    },
                    "slack_routing": {"channel_name": "#finops-alert-engineering"},
                },
                "correlation_id": "9b1deb4d-3b7d-4bad-9bdd-2b0d7b3dcb6d",
                "dry_run_mode": True,
            }
        }
    }
