from fastapi import FastAPI, Header, HTTPException, Request, status
from pydantic import BaseModel, Field
from typing import List, Optional, Union
import uuid
from datetime import datetime

app = FastAPI(
    title="FinOps Watch AI Engine - Skeleton",
    version="1.1.0",
    description="Skeleton API for Task Force 2 (FinOps Watch) early CDO integration."
)





class CESignal(BaseModel):
    date: str
    linked_account_id: str
    linked_account_name: str
    service_code: str
    service: str
    region: str
    unblended_cost: float
    cost_ratio_to_7d_avg: float
    day_of_week: int
    is_weekend: bool
    is_estimated: bool

class CURSignal(BaseModel):
    bill_billing_period_start_date: Optional[str] = None
    line_item_usage_start_date: str
    line_item_usage_end_date: Optional[str] = None
    line_item_usage_account_id: str
    line_item_usage_account_name: Optional[str] = None
    line_item_product_code: str
    line_item_usage_type: str
    line_item_operation: str
    line_item_resource_id: str
    line_item_usage_amount: float
    pricing_unit: str
    line_item_unblended_rate: float
    line_item_unblended_cost: float
    usage_density_24h: float
    resource_tags_user_environment: str
    resource_tags_user_team: Optional[str] = None
    resource_tags_user_owner: Optional[str] = None
    resource_tags_user_cost_center: Optional[str] = None

class UtilizationMetric(BaseModel):
    resource_id: str
    cpu_percent: float
    memory_mib: Optional[float] = None
    network_in_bytes: float
    network_out_bytes: float
    disk_io_ops: Optional[float] = None
    database_connections: Optional[int] = None
    gpu_utilization: Optional[float] = None
    idle_hours_continuous: Optional[int] = None

class DetectRequest(BaseModel):
    data_source_type: str
    is_ad_hoc: Optional[bool] = False
    telemetry_delay_event: Optional[bool] = False
    aws_cost_explorer_daily: List[CESignal]
    aws_cur_line_items: Optional[List[CURSignal]] = None
    s3_bucket_uri: Optional[str] = None
    resource_utilization_metrics: Optional[List[UtilizationMetric]] = None

class AlertRouting(BaseModel):
    finance: bool
    engineering: bool

class AnomalyItem(BaseModel):
    anomaly_id: str
    anomaly_type: str
    severity: str
    confidence_score: float
    resource_id: str
    environment: str
    responsible_team: Optional[str] = None
    unblended_cost_24h_usd: float
    cost_ratio_to_7d_avg: float
    ai_model_used: str
    alert_routing: AlertRouting

class DetectResponse(BaseModel):
    success: bool
    correlation_id: str
    anomalies_detected: bool
    anomalies_list: List[AnomalyItem]
    error_message: Optional[str] = None

class AnomalyContext(BaseModel):
    anomaly_id: str
    anomaly_type: str
    resource_id: str
    environment: str
    unblended_cost_24h_usd: float
    cost_ratio_to_7d_avg: float
    responsible_team: Optional[str] = None
    cost_center_code: Optional[str] = None

class DecideRequest(BaseModel):
    correlation_id: str
    idempotency_key: str
    dry_run_mode: bool
    anomaly_context: AnomalyContext

class ActionStep(BaseModel):
    step: int
    action: str
    target: str
    params: Optional[dict] = None

class AppliedPayload(BaseModel):
    action_type: str
    aws_cli_command: str

class RollbackPayload(BaseModel):
    action_type: str
    aws_cli_rollback_command: str
    original_resource_id: str

class FinanceMetrics(BaseModel):
    unblended_cost_24h_usd: float
    cost_ratio_to_7d_avg: float
    projected_monthly_waste_usd: float

class FinanceAllocation(BaseModel):
    responsible_team: str
    cost_center_code: str

class FinanceDashboardData(BaseModel):
    target_recipient: str
    metrics: FinanceMetrics
    allocation: FinanceAllocation
    executive_summary: str

class TechnicalContext(BaseModel):
    aws_service: str
    usage_type: str
    pricing_unit: str
    usage_amount_24h: float
    usage_density_24h: float

class RootCauseAnalysis(BaseModel):
    primary_driver_feature: str
    technical_reason: str
    missing_mandatory_tags: Optional[List[str]] = []

class EngineeringDashboardData(BaseModel):
    target_recipient: str
    technical_context: TechnicalContext
    root_cause_analysis: RootCauseAnalysis

class DecideResponse(BaseModel):
    matched_runbook: str
    action_plan: List[ActionStep]
    applied_payload: AppliedPayload
    rollback_payload: RollbackPayload
    finance_dashboard_data: FinanceDashboardData
    engineering_dashboard_data: EngineeringDashboardData
    correlation_id: str
    dry_run_mode: bool

class ActionExecuted(BaseModel):
    action: str
    target: str
    status: str
    execution_time_seconds: Optional[int] = 0

class PostTelemetryWindow(BaseModel):
    data_source_type: str
    aws_cost_explorer_daily: List[dict]
    aws_cur_line_items: Optional[List[dict]] = None
    s3_bucket_uri: Optional[str] = None

class VerifyRequest(BaseModel):
    correlation_id: str
    idempotency_key: str
    dry_run_mode: bool
    action_executed: ActionExecuted
    post_telemetry_window: PostTelemetryWindow

class EscalationBundle(BaseModel):
    reason: str
    logs: Optional[List[str]] = None
    metrics: Optional[dict] = None

class VerifyResponse(BaseModel):
    success: bool
    regression_detected: bool
    next_action: str
    escalation_bundle: Optional[EscalationBundle] = None

class RollbackRequest(BaseModel):
    reason: str
    rolled_back_by: str

class RollbackResponse(BaseModel):
    rollback_initiated: bool
    false_positive_count_updated: bool
    new_error_budget_burned_pct: float
    containment_locked: bool
    message: str





@app.post("/v1/detect", response_model=DetectResponse)
async def post_detect(
    request: DetectRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-Id"),
    x_idempotency_key: str = Header(..., alias="X-Idempotency-Key"),
    x_dry_run_mode: str = Header(..., alias="X-Dry-Run-Mode")
):

    corr_id = str(uuid.uuid4())
    return DetectResponse(
        success=True,
        correlation_id=corr_id,
        anomalies_detected=True,
        anomalies_list=[
            AnomalyItem(
                anomaly_id="ANM-2026-0623A",
                anomaly_type="runaway_usage",
                severity="HIGH",
                confidence_score=0.94,
                resource_id="i-0abcd1234efgh5678",
                environment="ml-research",
                responsible_team="squad-ml-core",
                unblended_cost_24h_usd=427.50,
                cost_ratio_to_7d_avg=18.2,
                ai_model_used="amazon.nova-pro-v1:0",
                alert_routing=AlertRouting(
                    finance=True,
                    engineering=True
                )
            )
        ]
    )

@app.get("/v1/status/{id}")
async def get_status(
    id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-Id")
):

    return {
        "audit_id": id,
        "status": "PENDING_APPROVAL",
        "containment_locked": False,
        "error_budget_remaining_pct": 97.3,
        "actions_log": [
            {
                "timestamp": datetime.utcnow().isoformat() + "Z",
                "action": "tag-for-review",
                "status": "DRY_RUN_COMPLETED",
                "actor": "finops-ai-engine-role"
            }
        ]
    }

@app.post("/v1/decide", response_model=DecideResponse)
async def post_decide(
    request: DecideRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-Id"),
    x_idempotency_key: str = Header(..., alias="X-Idempotency-Key")
):
    return DecideResponse(
        matched_runbook="RunawayMLClusterContainmentRunbook",
        action_plan=[
            ActionStep(
                step=1,
                action="tag-for-review",
                target=request.anomaly_context.resource_id,
                params={}
            ),
            ActionStep(
                step=2,
                action="time-gated-countdown",
                target=request.anomaly_context.resource_id,
                params={
                    "time_lock_seconds": 14400,
                    "fallback_action": "auto-shutdown"
                }
            )
        ],
        applied_payload=AppliedPayload(
            action_type="inject_aws_tag",
            aws_cli_command=f"aws ec2 create-tags --resources {request.anomaly_context.resource_id} --tags Key=finops:review,Value=pending Key=finops:anomaly-id,Value={request.anomaly_context.anomaly_id} --region ap-southeast-1"
        ),
        rollback_payload=RollbackPayload(
            action_type="remove_aws_tag",
            aws_cli_rollback_command=f"aws ec2 delete-tags --resources {request.anomaly_context.resource_id} --tags Key=finops:review Key=finops:anomaly-id --region ap-southeast-1",
            original_resource_id=request.anomaly_context.resource_id
        ),
        finance_dashboard_data=FinanceDashboardData(
            target_recipient="Finance Team & CFO Dashboard",
            metrics=FinanceMetrics(
                unblended_cost_24h_usd=request.anomaly_context.unblended_cost_24h_usd,
                cost_ratio_to_7d_avg=request.anomaly_context.cost_ratio_to_7d_avg,
                projected_monthly_waste_usd=request.anomaly_context.unblended_cost_24h_usd * 30
            ),
            allocation=FinanceAllocation(
                responsible_team=request.anomaly_context.responsible_team or "unknown",
                cost_center_code=request.anomaly_context.cost_center_code or "CC-GENERIC"
            ),
            executive_summary=f"Tài nguyên {request.anomaly_context.resource_id} thuộc squad {request.anomaly_context.responsible_team} đang phát sinh bất thường chi phí ở mức ${request.anomaly_context.unblended_cost_24h_usd}/ngày. Dự kiến lãng phí cả tháng lên tới ${request.anomaly_context.unblended_cost_24h_usd * 30} nếu không can thiệp."
        ),
        engineering_dashboard_data=EngineeringDashboardData(
            target_recipient="Engineering Console & Slack",
            technical_context=TechnicalContext(
                aws_service="AmazonEC2",
                usage_type="BoxUsage:g4dn.xlarge",
                pricing_unit="Hrs",
                usage_amount_24h=24.0,
                usage_density_24h=1.0
            ),
            root_cause_analysis=RootCauseAnalysis(
                primary_driver_feature="usage_density_24h",
                technical_reason="Tài nguyên chạy liên tục 24/7 với mật độ tối đa trong khi không có tác vụ tính toán training nào được kích hoạt. Nghi ngờ quên tắt instance.",
                missing_mandatory_tags=[]
            )
        ),
        correlation_id=request.correlation_id,
        dry_run_mode=request.dry_run_mode
    )

@app.post("/v1/verify", response_model=VerifyResponse)
async def post_verify(
    request: VerifyRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-Id"),
    x_idempotency_key: str = Header(..., alias="X-Idempotency-Key")
):
    return VerifyResponse(
        success=True,
        regression_detected=False,
        next_action="DONE"
    )

@app.get("/health")
async def get_health():
    return {
        "status": "healthy",
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "services": {
            "s3_audit_bucket": "connected",
            "bedrock_api": "accessible",
            "s3_cur_bucket": "reachable"
        }
    }

@app.post("/v1/audit/{audit_id}/rollback", response_model=RollbackResponse)
async def post_rollback(
    audit_id: str,
    request: RollbackRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-Id")
):
    return RollbackResponse(
        rollback_initiated=True,
        false_positive_count_updated=True,
        new_error_budget_burned_pct=0.5,
        containment_locked=False,
        message=f"Rollback cho sự cố {audit_id} đã được kích hoạt thành công bởi {request.rolled_back_by}."
    )
