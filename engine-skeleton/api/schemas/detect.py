"""
API request / response schemas for POST /v1/finops/detect
==========================================================
These are the *contract* schemas — they define what CDO sends and what CDO receives.
Internal domain models live separately in models/domain.py.

Schema is designed so that:
  - Adding optional fields is non-breaking (curveball safe)
  - Removing or renaming required fields is a breaking change (needs v2 path)
"""

from __future__ import annotations

from datetime import datetime
from typing import Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, Field

from models.enums import AnomalyType, AlertRoute, SuggestedAction


# ---------------------------------------------------------------------------
# Request schemas
# ---------------------------------------------------------------------------

class CostWindowItem(BaseModel):
    """Single cost data point within the analysis window.
    Fields aligned with CUR 2.0 schema (tf2-data/cur_line_items.csv).
    """
    # --- Required fields (CDO must always send) ---
    account_id: str                                     # line_item_usage_account_id
    service: str                                        # line_item_product_code (e.g. "AmazonEC2")
    region: str = "us-east-1"                           # product_region_code
    cost_usd: float = Field(ge=0.0)                     # line_item_unblended_cost
    usage_type: str = ""                                # line_item_usage_type
    tags: Dict[str, str] = Field(default_factory=dict)  # resource_tags_user_*
    environment: str = "unknown"                        # resource_tags_user_environment
    owner: Optional[str] = None                         # resource_tags_user_owner
    cost_period_start: datetime                         # line_item_usage_start_date
    cost_period_end: datetime                           # line_item_usage_end_date
    idempotency_key: Optional[str] = None

    # --- CUR 2.0 enrichment fields (optional, backward-compatible) ---
    account_name: Optional[str] = None                  # line_item_usage_account_name
    product_code: Optional[str] = None                  # line_item_product_code (canonical)
    operation: Optional[str] = None                     # line_item_operation
    resource_id: Optional[str] = None                   # line_item_resource_id (ARN)
    instance_type: Optional[str] = None                 # product_instance_type
    usage_amount: Optional[float] = None                # line_item_usage_amount
    pricing_unit: Optional[str] = None                  # pricing_unit (Hrs, GB...)
    unblended_rate: Optional[float] = None              # line_item_unblended_rate
    is_estimated: bool = False                          # Cost Explorer is_estimated flag
    cost_center: Optional[str] = None                   # resource_tags_user_cost_center


class BaselineMetadata(BaseModel):
    """Metadata describing the baseline comparison window."""
    baseline_start: datetime
    baseline_end: datetime
    baseline_avg_daily_cost_usd: Optional[float] = None
    baseline_total_cost_usd: Optional[float] = None


class ContainmentPolicy(BaseModel):
    """Optional caller-supplied containment preferences."""
    allow_auto_containment: bool = False
    allowed_environments: List[str] = Field(default_factory=lambda: ["dev", "sandbox"])
    max_cost_impact_usd: Optional[float] = None


class DetectRequest(BaseModel):
    """
    POST /v1/finops/detect request body.
    Aligned with TF2 AI API Contract + Telemetry Contract fields.
    """
    cost_window: List[CostWindowItem] = Field(
        ...,
        min_length=1,
        description="Cost data points for the analysis window",
    )
    baseline: Optional[BaselineMetadata] = Field(
        default=None,
        description="Baseline window metadata for comparison",
    )
    detection_cadence_hours: int = Field(
        default=24,
        ge=1,
        le=168,
        description="Detection cadence in hours (12/24/48)",
    )
    containment_policy: Optional[ContainmentPolicy] = None

    model_config = {"json_schema_extra": {
        "example": {
            "cost_window": [
                {
                    "account_id": "200000000015",
                    "service": "AmazonEC2",
                    "region": "us-east-1",
                    "cost_usd": 73.44,
                    "usage_type": "BoxUsage:p3.2xlarge",
                    "tags": {"team": "ml-research", "environment": "dev"},
                    "environment": "dev",
                    "owner": "ml-team@company.com",
                    "cost_period_start": "2026-05-15T00:00:00Z",
                    "cost_period_end": "2026-05-16T00:00:00Z",
                    "account_name": "ml-research",
                    "product_code": "AmazonEC2",
                    "operation": "RunInstances",
                    "resource_id": "i-gpu-training-forgotten-01",
                    "instance_type": "p3.2xlarge",
                    "usage_amount": 24.0,
                    "pricing_unit": "Hrs",
                    "unblended_rate": 3.06,
                    "is_estimated": False,
                    "cost_center": "CC-1005",
                }
            ],
            "baseline": {
                "baseline_start": "2026-03-01T00:00:00Z",
                "baseline_end": "2026-04-30T00:00:00Z",
                "baseline_avg_daily_cost_usd": 50.0,
                "baseline_total_cost_usd": 3050.0,
            },
            "detection_cadence_hours": 24,
        }
    }}


# ---------------------------------------------------------------------------
# Response schemas
# ---------------------------------------------------------------------------

class ContainmentDetail(BaseModel):
    """Details about the containment decision."""
    action: SuggestedAction
    target_resource: Optional[str] = None
    target_environment: str = "unknown"
    dry_run_required: bool = True
    dry_run_passed: Optional[bool] = None
    rollback_path: Optional[str] = None


class DetectResponse(BaseModel):
    """
    POST /v1/finops/detect response body.
    Aligned with TF2 operating flow §6 response spec.
    """
    anomaly: bool
    anomaly_type: AnomalyType = AnomalyType.OTHER
    severity: float = Field(ge=0.0, le=1.0)
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: str = Field(max_length=300)
    finance_summary: str = Field(
        description="Finance-friendly explanation (no technical jargon)",
    )
    engineering_summary: str = Field(
        description="Engineering-focused details (service, owner, action)",
    )
    alert_route: AlertRoute
    suggested_action: SuggestedAction
    containment: Optional[ContainmentDetail] = None
    dry_run_required: bool = True
    audit_id: UUID
    detected_at: datetime
    affected_resource_id: Optional[str] = Field(
        default=None,
        description="Resource ID/ARN that triggered the anomaly (for CDO drill-down)",
    )

    model_config = {"json_schema_extra": {
        "example": {
            "anomaly": True,
            "anomaly_type": "runaway_usage",
            "severity": 0.85,
            "confidence": 0.78,
            "reasoning": "EC2 p3.2xlarge in dev account 200000000015 (ml-research) running 24/7, cost $73.44/day vs baseline $50/day — 147% spike.",
            "finance_summary": "Dev GPU compute overspend: $23.44/day above expected in ml-research account. Recommend immediate review.",
            "engineering_summary": "Account: 200000000015 (ml-research) | Service: AmazonEC2 | Resource: i-gpu-training-forgotten-01 | Type: p3.2xlarge | Delta: +$23.44/day",
            "alert_route": "both",
            "suggested_action": "schedule_shutdown",
            "containment": {
                "action": "schedule_shutdown",
                "target_resource": "i-gpu-training-forgotten-01",
                "target_environment": "dev",
                "dry_run_required": True,
                "dry_run_passed": None,
                "rollback_path": "Re-launch resource via AWS Console or IaC re-apply",
            },
            "dry_run_required": True,
            "audit_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
            "detected_at": "2026-06-23T10:30:00Z",
            "affected_resource_id": "i-gpu-training-forgotten-01",
        }
    }}


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------

class HealthResponse(BaseModel):
    """GET /health response."""
    status: str = "healthy"
    version: str
    environment: str
    engine_mode: str = "skeleton"
    checks: Dict[str, str] = Field(default_factory=dict)
