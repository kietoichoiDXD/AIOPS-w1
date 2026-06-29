from __future__ import annotations

from typing import Any
from pydantic import BaseModel, Field, field_validator, model_validator
from app.models.enums import (
    AnomalyType, DataSourceType, Severity, DataConfidence, TrafficSource,
)




class CEDailyItem(BaseModel):
    """One row from aws_cost_explorer_daily (macro-level daily grain)."""


    date: str = Field(..., description="Date in YYYY-MM-DD format", examples=["2026-06-23"])
    linked_account_id: str = Field(..., pattern=r"^\d{12}$", description="12-digit AWS account ID")
    linked_account_name: str = Field(..., description="Human-readable account name")
    service_code: str = Field(..., description="AWS service code, e.g. AmazonEC2")
    service: str = Field(..., description="Full CE display name")
    unblended_cost: float = Field(..., ge=0, description="Unblended cost in USD")
    is_estimated: bool = Field(..., description="True if CE cost is still estimated/unfinalized")

    region: str | None = Field(None, description="AWS region; null/'global' for global services")
    cost_ratio_to_7d_avg: float | None = Field(None, ge=0, description="Cost ratio vs trailing 7-day average")
    day_of_week: int | None = Field(None, ge=0, le=6, description="0=Monday … 6=Sunday")
    is_weekend: bool | None = Field(None, description="True if Saturday or Sunday")

    model_config = {
        "json_schema_extra": {
            "example": {
                "date": "2026-06-23",
                "linked_account_id": "200000000012",
                "linked_account_name": "squad-ml-research",
                "service_code": "AmazonEC2",
                "service": "Amazon Elastic Compute Cloud - Compute",
                "region": "ap-southeast-1",
                "unblended_cost": 427.50,
                "cost_ratio_to_7d_avg": 18.2,
                "day_of_week": 1,
                "is_weekend": False,
                "is_estimated": False,
            }
        }
    }


class CURLineItem(BaseModel):
    """One resource-level CUR line item (micro-level detail)."""

    bill_billing_period_start_date: str | None = Field(None, description="Billing period start (ISO 8601)")
    line_item_usage_start_date: str = Field(..., description="Usage interval start (ISO 8601)")
    line_item_usage_end_date: str | None = Field(None, description="Usage interval end (ISO 8601)")
    line_item_usage_account_id: str = Field(..., pattern=r"^\d{12}$")
    line_item_usage_account_name: str | None = None
    line_item_product_code: str = Field(..., description="AWS product code, e.g. AmazonEC2")
    line_item_usage_type: str = Field(..., description="Usage type string, e.g. BoxUsage:g4dn.xlarge")
    line_item_operation: str | None = None
    line_item_resource_id: str = Field(..., description="Resource ARN or logical ID")
    line_item_usage_amount: float = Field(..., ge=0)
    pricing_unit: str = Field(..., description="Billing unit, e.g. Hrs, GB, GB-Mo")
    line_item_unblended_rate: float | None = Field(None, ge=0)
    line_item_unblended_cost: float = Field(..., ge=0)


    usage_density_24h: float | None = Field(None, ge=0, le=1, description="Utilization ratio for Hrs-billed services")
    resource_tags_user_environment: str | None = Field(None, description="Environment tag value (null/unknown when untagged)")
    resource_tags_user_team: str | None = None
    resource_tags_user_owner: str | None = None
    resource_tags_user_cost_center: str | None = None

    model_config = {"extra": "allow"}


class ResourceUtilizationMetric(BaseModel):
    """CloudWatch metric snapshot for one resource."""


    resource_id: str = Field(..., description="Resource ARN or instance ID")
    cpu_percent: float | None = Field(None, ge=0, le=100, description="Average CPU utilisation (%)")
    memory_mib: float | None = Field(None, ge=0)
    network_in_bytes: float | None = Field(None, ge=0)
    network_out_bytes: float | None = Field(None, ge=0)
    disk_io_ops: float | None = Field(None, ge=0)
    database_connections: int | None = Field(None, ge=0)
    gpu_utilization: float | None = Field(None, ge=0, le=100)


    cpu_utilization_hourly: list[float] | None = Field(
        None, max_length=24, description="24 per-hour avg CPU values (contract name)",
    )
    hourly_cpu_percent: list[float] | None = Field(
        None, max_length=24, description="Alias of cpu_utilization_hourly (legacy)",
    )

    @model_validator(mode="after")
    def _sync_hourly(self) -> "ResourceUtilizationMetric":

        if self.cpu_utilization_hourly and not self.hourly_cpu_percent:
            self.hourly_cpu_percent = self.cpu_utilization_hourly
        elif self.hourly_cpu_percent and not self.cpu_utilization_hourly:
            self.cpu_utilization_hourly = self.hourly_cpu_percent
        return self

    model_config = {"extra": "allow"}


class BusinessContext(BaseModel):
    """Per-batch business signal (contract §5.1 / telemetry §11.2). Required."""

    linked_account_id: str = Field(..., pattern=r"^\d{12}$", description="Account scope for traffic_volume")
    traffic_volume: float = Field(..., ge=0, description="Request/traffic volume for the batch window")
    traffic_source: TrafficSource = Field(..., description="ALB | CloudFront | ApiGateway | Synthetic | Mixed")
    campaign_flag: bool = Field(..., description="True if a marketing campaign is active (benign-cost context)")
    load_test_flag: bool = Field(..., description="True if a load test is running (benign-cost context)")
    migration_flag: bool = Field(..., description="True if a data migration is running (benign-cost context)")
    active_users: int | None = Field(None, ge=0)
    orders_count: int | None = Field(None, ge=0)

    model_config = {"extra": "allow"}


class ComparisonWindow(BaseModel):
    """Date window for the CE-fallback gap (contract §5.1, telemetry §6.2)."""

    start_date: str = Field(..., description="YYYY-MM-DD")
    end_date: str = Field(..., description="YYYY-MM-DD")


class DetectRequest(BaseModel):
    """Request body for POST /v1/detect (contract v1.5.0 §5.1)."""

    data_source_type: DataSourceType = Field(
        ..., description="RAW_JSON = inline data; S3_POINTER = S3 URI"
    )
    business_context: BusinessContext = Field(
        ..., description="Required every batch — traffic/campaign context for FP suppression"
    )
    is_ad_hoc: bool = Field(False, description="True = emergency scan, bypasses idempotency")
    telemetry_delay_event: bool = Field(
        False,
        description="True = CUR not yet finalized; AI Engine falls back to CE and lowers confidence",
    )

    aws_cost_explorer_daily: list[CEDailyItem] | None = Field(
        None, description="CE daily rows — required only when telemetry_delay_event=true"
    )
    missing_resources: list[str] | None = Field(
        None, description="Required when telemetry_delay_event=true: service codes in CE but not yet in CUR"
    )
    current_ce_cost_gap_usd: float | None = Field(
        None, ge=0, description="Required when telemetry_delay_event=true: total USD gap of missing_resources"
    )
    comparison_window: ComparisonWindow | None = Field(
        None, description="Required when telemetry_delay_event=true"
    )
    aws_cur_line_items: list[CURLineItem] | None = Field(
        None, description="Required when data_source_type=RAW_JSON and telemetry_delay_event=false"
    )
    s3_bucket_uri: str | None = Field(
        None,
        pattern=r"^s3://company-cdo-\d{12}-telemetry/.+\.(json|csv)\.gz$",
        description=(
            "Required when data_source_type=S3_POINTER. Bucket: company-cdo-{account_id}-telemetry. "
            "Accepts .json.gz (Athena export) or .csv.gz (native AWS CUR — no conversion needed)."
        ),
    )
    callback_url: str | None = Field(
        None, pattern=r"^https://", description="Optional: AI Engine POSTs a copy of DetectResponse after 200 (audit)"
    )
    callback_token: str | None = Field(
        None, description="Optional: echoed in X-Callback-Token on the callback"
    )
    resource_utilization_metrics: list[ResourceUtilizationMetric] | None = Field(
        None, description="Optional CloudWatch utilisation snapshots"
    )

    @model_validator(mode="after")
    def _validate_source_type(self) -> "DetectRequest":
        if self.telemetry_delay_event:

            missing = [
                name for name, val in [
                    ("aws_cost_explorer_daily", self.aws_cost_explorer_daily),
                    ("missing_resources", self.missing_resources),
                    ("current_ce_cost_gap_usd", self.current_ce_cost_gap_usd),
                    ("comparison_window", self.comparison_window),
                ] if val is None
            ]
            if missing:
                raise ValueError(
                    f"telemetry_delay_event=true requires: {', '.join(missing)}"
                )
            return self

        if self.data_source_type == DataSourceType.RAW_JSON and not self.aws_cur_line_items:
            raise ValueError("aws_cur_line_items is required when data_source_type=RAW_JSON")
        if self.data_source_type == DataSourceType.S3_POINTER and not self.s3_bucket_uri:
            raise ValueError("s3_bucket_uri is required when data_source_type=S3_POINTER")
        return self

    model_config = {
        "json_schema_extra": {
            "example": {
                "data_source_type": "RAW_JSON",
                "is_ad_hoc": False,
                "telemetry_delay_event": False,
                "business_context": {
                    "linked_account_id": "200000000012",
                    "traffic_volume": 1250000,
                    "traffic_source": "ALB",
                    "campaign_flag": False,
                    "load_test_flag": False,
                    "migration_flag": False,
                },
                "aws_cost_explorer_daily": [
                    {
                        "date": "2026-06-23",
                        "linked_account_id": "200000000012",
                        "linked_account_name": "squad-ml-research",
                        "service_code": "AmazonEC2",
                        "service": "Amazon Elastic Compute Cloud - Compute",
                        "region": "ap-southeast-1",
                        "unblended_cost": 427.50,
                        "cost_ratio_to_7d_avg": 18.2,
                        "day_of_week": 1,
                        "is_weekend": False,
                        "is_estimated": False,
                    }
                ],
                "aws_cur_line_items": [
                    {
                        "line_item_usage_start_date": "2026-06-23T00:00:00Z",
                        "line_item_usage_account_id": "200000000012",
                        "line_item_product_code": "AmazonEC2",
                        "line_item_usage_type": "BoxUsage:g4dn.xlarge",
                        "line_item_resource_id": "i-0abcd1234efgh5678",
                        "line_item_usage_amount": 24.0,
                        "pricing_unit": "Hrs",
                        "line_item_unblended_cost": 427.50,
                        "usage_density_24h": 1.0,
                        "resource_tags_user_environment": "ml-research",
                    }
                ],
            }
        }
    }




class AlertRouting(BaseModel):
    """Which dashboards should receive this anomaly alert."""

    finance: bool = Field(..., description="Route to Finance Dashboard")
    engineering: bool = Field(..., description="Route to Engineering Console")


class AnomalyItem(BaseModel):
    """One detected anomaly in the detect response."""

    anomaly_id: str = Field(
        ...,
        pattern=r"^ANM-\d{4}-\d{4}[A-Z]$",
        description="Unique anomaly ID, format: ANM-YYYY-MMDD{A-Z}",
    )
    anomaly_type: AnomalyType
    severity: Severity
    confidence_score: float = Field(..., ge=0.0, le=1.0)
    resource_id: str = Field(..., description="AWS resource ARN or logical ID")
    environment: str = Field(..., description="Environment tag of the resource")
    responsible_team: str | None = Field(None, description="Team tag of the resource")
    unblended_cost_24h_usd: float = Field(..., ge=0, description="24h cost in USD")
    cost_ratio_to_7d_avg: float = Field(..., ge=0, description="Cost ratio vs trailing 7-day average")
    ai_model_used: str = Field(..., description="Model or rule that produced this finding")
    alert_routing: AlertRouting

    model_config = {
        "json_schema_extra": {
            "example": {
                "anomaly_id": "ANM-2026-0626A",
                "anomaly_type": "runaway_usage",
                "severity": "HIGH",
                "confidence_score": 0.94,
                "resource_id": "i-0abcd1234efgh5678",
                "environment": "ml-research",
                "responsible_team": "squad-ml-core",
                "unblended_cost_24h_usd": 427.50,
                "cost_ratio_to_7d_avg": 18.2,
                "ai_model_used": "mock-isolation-forest-v1",
                "alert_routing": {"finance": True, "engineering": True},
            }
        }
    }


class DetectResponse(BaseModel):
    """Response body for POST /v1/detect."""

    success: bool = Field(..., description="True if processing completed without error")
    correlation_id: str = Field(..., description="UUID v4 trace ID for this detection session")
    anomalies_detected: bool = Field(..., description="True if at least one anomaly was found")
    data_confidence: DataConfidence = Field(
        DataConfidence.HIGH,
        description="HIGH = CUR complete; LOW = CE fallback (telemetry_delay_event)",
    )
    anomalies_list: list[AnomalyItem] = Field(..., description="List of detected anomalies (may be empty)")
    error_message: str | None = Field(None, description="Populated only when success=false")

    model_config = {
        "json_schema_extra": {
            "example": {
                "success": True,
                "correlation_id": "9b1deb4d-3b7d-4bad-9bdd-2b0d7b3dcb6d",
                "anomalies_detected": True,
                "data_confidence": "HIGH",
                "anomalies_list": [
                    {
                        "anomaly_id": "ANM-2026-0626A",
                        "anomaly_type": "runaway_usage",
                        "severity": "HIGH",
                        "confidence_score": 0.94,
                        "resource_id": "i-0abcd1234efgh5678",
                        "environment": "ml-research",
                        "responsible_team": "squad-ml-core",
                        "unblended_cost_24h_usd": 427.50,
                        "cost_ratio_to_7d_avg": 18.2,
                        "ai_model_used": "mock-isolation-forest-v1",
                        "alert_routing": {"finance": True, "engineering": True},
                    }
                ],
            }
        }
    }
