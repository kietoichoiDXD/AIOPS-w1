from __future__ import annotations

from pydantic import BaseModel, Field
from app.models.enums import ContainmentAction, RemediationStatus


class ActionLogEntry(BaseModel):
    timestamp: str = Field(..., description="RFC3339 UTC timestamp of this action")
    action: ContainmentAction
    status: str = Field(..., description="e.g. COMPLETED, DRY_RUN_COMPLETED, FAILED")
    actor: str = Field(..., description="Actor that executed the step")


class RemediationStatusResponse(BaseModel):
    """Response body for GET /v1/status/{id}."""

    audit_id: str = Field(
        ...,
        description="Audit-record identifier (UUID v4) — audit chain, telemetry §16",
    )
    anomaly_id: str = Field(
        ...,
        pattern=r"^ANM-\d{4}-\d{4}[A-Z]$",
        description="Anomaly ID (ANM-YYYY-MMDD{A-Z}) — matches the path param",
    )
    status: RemediationStatus
    containment_locked: bool = Field(
        ..., description="True if tenant is in LOCKED_MODE (dry-run only)"
    )
    error_budget_remaining_pct: float = Field(
        ..., ge=0, le=100, description="Error budget remaining (0–100 %)"
    )
    actions_log: list[ActionLogEntry] = Field(..., description="Ordered history of steps taken")

    model_config = {
        "json_schema_extra": {
            "example": {
                "audit_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
                "anomaly_id": "ANM-2026-0626A",
                "status": "PENDING_APPROVAL",
                "containment_locked": False,
                "error_budget_remaining_pct": 97.3,
                "actions_log": [
                    {
                        "timestamp": "2026-06-26T10:05:46Z",
                        "action": "tag-for-review",
                        "status": "DRY_RUN_COMPLETED",
                        "actor": "finops-ai-engine-role",
                    }
                ],
            }
        }
    }




class RollbackRequest(BaseModel):
    """Request body for POST /v1/audit/{audit_id}/rollback."""

    reason: str = Field(..., description="Why the rollback was triggered (e.g. False Positive)")
    rolled_back_by: str = Field(..., description="Email of engineer who initiated rollback")

    model_config = {
        "json_schema_extra": {
            "example": {
                "reason": "False positive — instance is used for approved experiment",
                "rolled_back_by": "engineer@company.com",
            }
        }
    }


class RollbackResponse(BaseModel):
    """Response body for POST /v1/audit/{audit_id}/rollback."""

    rollback_recorded: bool = Field(..., description="True if audit log was updated")
    false_positive_count_updated: bool = Field(
        ..., description="True if FP counter was incremented for model feedback"
    )
    new_error_budget_burned_pct: float = Field(
        ..., ge=0, description="Updated error budget burn percentage after this event"
    )
    containment_locked: bool = Field(
        ..., description="True if LOCKED_MODE was triggered by this rollback"
    )
    message: str = Field(..., description="Human-readable system message")

    model_config = {
        "json_schema_extra": {
            "example": {
                "rollback_recorded": True,
                "false_positive_count_updated": True,
                "new_error_budget_burned_pct": 1.5,
                "containment_locked": True,
                "message": "Error budget exceeded 1%. Tenant switched to LOCKED_MODE — all containment actions will be dry-run only.",
            }
        }
    }
