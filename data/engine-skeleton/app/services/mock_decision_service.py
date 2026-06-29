"""
Mock implementation of DecisionService.

Decision rules follow the ai-api-contract §7 exactly:
  prod / prod-core / prod-payments  → tag-for-review only
  staging                           → time-gated-countdown
  dev / sandbox                     → auto-shutdown
  ml-research                       → auto-shutdown (SageMaker → stop_sagemaker_notebook)
  data-analytics                    → quota-cap

Replace this class with a real runbook engine + Nova integration
without touching any router or schema code.
"""

import datetime
import random

from app.config.settings import settings
from app.models.enums import (
    AnomalyType,
    AppliedActionType,
    ContainmentAction,
    Environment,
    NextAction,
    RemediationStatus,
    RollbackActionType,
)
from app.schemas.decide import (
    ActionPlanStep,
    AppliedPayload,
    DecideRequest,
    DecideResponse,
    EngineeringDashboardData,
    FinanceDashboardData,
    FinanceAllocation,
    FinanceMetrics,
    RollbackPayload,
    RootCauseAnalysis,
    SlackRouting,
    TechnicalContext,
)
from app.schemas.status import ActionLogEntry, RollbackRequest, RollbackResponse
from app.schemas.verify import EscalationBundle, EscalationMetrics, VerifyRequest, VerifyResponse
from app.services.base import DecisionService
from app.services.mock_detect_service import MockDetectService

_REGION = "ap-southeast-1"

_RUNBOOK_MAP: dict[AnomalyType, str] = {
    AnomalyType.runaway_usage: "RunawayMLClusterContainmentRunbook",
    AnomalyType.idle_resource: "IdleResourceDecommissionRunbook",
    AnomalyType.untagged_spend: "UntaggedSpendRemediationRunbook",
    AnomalyType.sudden_spike: "SuddenSpikeContainmentRunbook",
    AnomalyType.gradual_drift: "GradualDriftQuotaCapRunbook",
}

_TECHNICAL_CONTEXT_MAP: dict[AnomalyType, dict] = {
    AnomalyType.runaway_usage: {
        "aws_service": "AmazonEC2",
        "usage_type": "BoxUsage:g4dn.xlarge",
        "pricing_unit": "Hrs",
        "usage_amount_24h": 24.0,
        "usage_density_24h": 1.0,
    },
    AnomalyType.idle_resource: {
        "aws_service": "AmazonRDS",
        "usage_type": "InstanceUsage:db.r5.2xlarge",
        "pricing_unit": "Hrs",
        "usage_amount_24h": 24.0,
        "usage_density_24h": 0.02,
    },
    AnomalyType.untagged_spend: {
        "aws_service": "AmazonEC2",
        "usage_type": "BoxUsage:m5.4xlarge",
        "pricing_unit": "Hrs",
        "usage_amount_24h": 24.0,
        "usage_density_24h": 0.85,
    },
    AnomalyType.sudden_spike: {
        "aws_service": "AmazonCloudWatch",
        "usage_type": "DataProcessing-Bytes",
        "pricing_unit": "GB",
        "usage_amount_24h": 2048.0,
        "usage_density_24h": 0.0,
    },
    AnomalyType.gradual_drift: {
        "aws_service": "AWSDataTransfer",
        "usage_type": "DataTransfer-Out-Bytes",
        "pricing_unit": "GB",
        "usage_amount_24h": 5120.0,
        "usage_density_24h": 0.0,
    },
}

_RCA_MAP: dict[AnomalyType, dict] = {
    AnomalyType.runaway_usage: {
        "primary_driver_feature": "usage_density_24h",
        "technical_reason": (
            "Instance running 100% of the 24-hour window (usage_density_24h=1.0). "
            "No training job found in SageMaker job history for the past 3 days. "
            "Suspected: developer forgot to stop instance after experiment completed."
        ),
        "missing_mandatory_tags": [],
    },
    AnomalyType.idle_resource: {
        "primary_driver_feature": "database_connections",
        "technical_reason": (
            "db.r5.2xlarge provisioned and billed continuously but database_connections=0 "
            "for >72 hours. Resource appears orphaned after a migration test."
        ),
        "missing_mandatory_tags": [],
    },
    AnomalyType.untagged_spend: {
        "primary_driver_feature": "resource_tags_user_team",
        "technical_reason": (
            "Resource incurring >$200/day has no team or owner tag. "
            "Cannot route alert to responsible squad."
        ),
        "missing_mandatory_tags": ["resource_tags_user_team", "resource_tags_user_owner"],
    },
    AnomalyType.sudden_spike: {
        "primary_driver_feature": "cost_ratio_to_7d_avg",
        "technical_reason": (
            "CloudWatch Logs ingest spiked >10× 7-day average in a single day. "
            "Suspected cause: DEBUG log level left enabled in a hot Lambda execution path."
        ),
        "missing_mandatory_tags": [],
    },
    AnomalyType.gradual_drift: {
        "primary_driver_feature": "cost_rolling_7d_slope",
        "technical_reason": (
            "Data transfer out-bytes increasing ~7% week-over-week for 4 consecutive weeks. "
            "Likely caused by expanding dataset replication without quota enforcement."
        ),
        "missing_mandatory_tags": [],
    },
}

_SLACK_CHANNELS: dict[str, str] = {
    "prod": "#finops-alert-prod",
    "prod-core": "#finops-alert-prod",
    "prod-payments": "#finops-alert-prod",
    "staging": "#finops-alert-staging",
    "dev": "#finops-alert-dev",
    "sandbox": "#finops-alert-dev",
    "ml-research": "#finops-alert-ml",
    "data-analytics": "#finops-alert-data",
}


_error_budget_store: dict[str, float] = {}


def _determine_containment(env: str, anomaly_type: AnomalyType, resource_id: str) -> ContainmentAction:
    """Deterministic containment rule per contract §7."""
    prod_envs = {"prod", "prod-core", "prod-payments"}
    if env in prod_envs:
        return ContainmentAction.tag_for_review
    if env == "staging":
        return ContainmentAction.time_gated_countdown
    if env in {"dev", "sandbox"}:
        return ContainmentAction.auto_shutdown
    if env == "ml-research":

        if "notebook" in resource_id.lower() or anomaly_type == AnomalyType.runaway_usage:
            return ContainmentAction.auto_shutdown
        return ContainmentAction.auto_shutdown
    if env == "data-analytics":
        return ContainmentAction.quota_cap
    return ContainmentAction.tag_for_review


def _build_action_plan(
    containment: ContainmentAction, resource_id: str
) -> list[ActionPlanStep]:
    steps = [
        ActionPlanStep(step=1, action=ContainmentAction.tag_for_review, target=resource_id, params={})
    ]
    if containment == ContainmentAction.time_gated_countdown:
        steps.append(
            ActionPlanStep(
                step=2,
                action=ContainmentAction.time_gated_countdown,
                target=resource_id,
                params={"time_lock_seconds": 14400, "fallback_action": "auto-shutdown"},
            )
        )
    elif containment == ContainmentAction.auto_shutdown:
        steps.append(
            ActionPlanStep(step=2, action=ContainmentAction.auto_shutdown, target=resource_id, params={})
        )
    elif containment == ContainmentAction.quota_cap:
        steps.append(
            ActionPlanStep(
                step=2,
                action=ContainmentAction.quota_cap,
                target=resource_id,
                params={"new_quota_value": "10GB", "service": "AWSDataTransfer"},
            )
        )
    return steps


def _build_applied_payload(containment: ContainmentAction, resource_id: str, anomaly_id: str) -> AppliedPayload:
    is_sagemaker = "notebook" in resource_id.lower()
    is_rds = "rds" in resource_id.lower() or "db:" in resource_id.lower()

    if containment == ContainmentAction.tag_for_review:
        return AppliedPayload(
            action_type=AppliedActionType.inject_aws_tag,
            aws_cli_command=(
                f"aws ec2 create-tags --resources {resource_id} "
                f"--tags Key=finops:review,Value=pending Key=finops:anomaly-id,Value={anomaly_id} "
                f"--region {_REGION}"
            ),
        )
    if containment == ContainmentAction.auto_shutdown:
        if is_sagemaker:
            return AppliedPayload(
                action_type=AppliedActionType.stop_sagemaker_notebook,
                aws_cli_command=(
                    f"aws sagemaker stop-notebook-instance --notebook-instance-name {resource_id} "
                    f"--region {_REGION}"
                ),
            )
        if is_rds:
            return AppliedPayload(
                action_type=AppliedActionType.stop_instance,
                aws_cli_command=(
                    f"aws rds stop-db-instance --db-instance-identifier {resource_id} "
                    f"--region {_REGION}"
                ),
            )
        return AppliedPayload(
            action_type=AppliedActionType.stop_instance,
            aws_cli_command=f"aws ec2 stop-instances --instance-ids {resource_id} --region {_REGION}",
        )
    if containment in (ContainmentAction.time_gated_countdown, ContainmentAction.quota_cap):
        return AppliedPayload(
            action_type=AppliedActionType.inject_aws_tag,
            aws_cli_command=(
                f"aws ec2 create-tags --resources {resource_id} "
                f"--tags Key=finops:review,Value=pending Key=finops:anomaly-id,Value={anomaly_id} "
                f"--region {_REGION}"
            ),
        )
    return AppliedPayload(
        action_type=AppliedActionType.inject_aws_tag,
        aws_cli_command=(
            f"aws ec2 create-tags --resources {resource_id} "
            f"--tags Key=finops:review,Value=pending --region {_REGION}"
        ),
    )


def _build_rollback_payload(containment: ContainmentAction, resource_id: str) -> RollbackPayload:
    is_sagemaker = "notebook" in resource_id.lower()
    is_rds = "rds" in resource_id.lower() or "db:" in resource_id.lower()

    if containment == ContainmentAction.tag_for_review or containment == ContainmentAction.time_gated_countdown:
        return RollbackPayload(
            action_type=RollbackActionType.remove_aws_tag,
            aws_cli_rollback_command=(
                f"aws ec2 delete-tags --resources {resource_id} "
                f"--tags Key=finops:review Key=finops:anomaly-id --region {_REGION}"
            ),
            original_resource_id=resource_id,
        )
    if containment == ContainmentAction.auto_shutdown:
        if is_sagemaker:
            return RollbackPayload(
                action_type=RollbackActionType.start_sagemaker_notebook,
                aws_cli_rollback_command=(
                    f"aws sagemaker start-notebook-instance --notebook-instance-name {resource_id} "
                    f"--region {_REGION}"
                ),
                original_resource_id=resource_id,
            )
        if is_rds:
            return RollbackPayload(
                action_type=RollbackActionType.start_instance,
                aws_cli_rollback_command=(
                    f"aws rds start-db-instance --db-instance-identifier {resource_id} "
                    f"--region {_REGION}"
                ),
                original_resource_id=resource_id,
            )
        return RollbackPayload(
            action_type=RollbackActionType.start_instance,
            aws_cli_rollback_command=f"aws ec2 start-instances --instance-ids {resource_id} --region {_REGION}",
            original_resource_id=resource_id,
        )
    return RollbackPayload(
        action_type=RollbackActionType.remove_aws_tag,
        aws_cli_rollback_command=(
            f"aws ec2 delete-tags --resources {resource_id} "
            f"--tags Key=finops:review --region {_REGION}"
        ),
        original_resource_id=resource_id,
    )


class MockDecisionService(DecisionService):
    """
    Mock decision, verify, and rollback service.

    Follows contract §7 decision rules deterministically.
    Verify outcome is probabilistic: 85% DONE, 10% RETRY, 4% ROLLBACK, 1% ESCALATE.
    """

    def __init__(self, detect_service: MockDetectService) -> None:
        self._detect = detect_service

    def decide(self, request: DecideRequest) -> DecideResponse:
        ctx = request.anomaly_context
        env = ctx.environment.value
        containment = _determine_containment(env, ctx.anomaly_type, ctx.resource_id)
        action_plan = _build_action_plan(containment, ctx.resource_id)
        applied = _build_applied_payload(containment, ctx.resource_id, ctx.anomaly_id)
        rollback = _build_rollback_payload(containment, ctx.resource_id)

        tech_ctx_data = _TECHNICAL_CONTEXT_MAP[ctx.anomaly_type]
        rca_data = _RCA_MAP[ctx.anomaly_type]

        projected = round(ctx.unblended_cost_24h_usd * 30, 2)
        cost_center = ctx.cost_center_code or "CC-UNKNOWN"
        team = ctx.responsible_team or "UNASSIGNED"

        finance_summary = (
            f"Resource {ctx.resource_id} ({team}) detected as {ctx.anomaly_type.value.replace('_', ' ')}. "
            f"Waste: ${ctx.unblended_cost_24h_usd:.2f}/day ({ctx.cost_ratio_to_7d_avg:.1f}× 7d avg). "
            f"Projected monthly waste: ${projected:,.2f}. "
            f"Containment action initiated (dry_run={request.dry_run_mode})."
        )

        finance = FinanceDashboardData(
            target_recipient="Finance Team & CFO Dashboard",
            metrics=FinanceMetrics(
                unblended_cost_24h_usd=ctx.unblended_cost_24h_usd,
                cost_ratio_to_7d_avg=ctx.cost_ratio_to_7d_avg,
                projected_monthly_waste_usd=projected,
            ),
            allocation=FinanceAllocation(responsible_team=team, cost_center_code=cost_center),
            executive_summary=finance_summary,
        )

        engineering = EngineeringDashboardData(
            target_recipient=f"Engineering Console & Slack {_SLACK_CHANNELS.get(env, '#finops-alert')}",
            technical_context=TechnicalContext(**tech_ctx_data),
            root_cause_analysis=RootCauseAnalysis(**rca_data),
            slack_routing=SlackRouting(
                channel_name=_SLACK_CHANNELS.get(env, "#finops-alert"),
                webhook_url_pointer=f"ssm:/finops-watch/{env}/slack-webhook",
            ),
        )


        now_iso = datetime.datetime.utcnow().isoformat() + "Z"
        log_entry = ActionLogEntry(
            timestamp=now_iso,
            action=action_plan[0].action,
            status="DRY_RUN_COMPLETED" if request.dry_run_mode else "COMPLETED",
            actor="finops-ai-engine-role",
        )
        MockDetectService.update_status(ctx.anomaly_id, RemediationStatus.IN_PROGRESS, log_entry)

        return DecideResponse(
            matched_runbook=_RUNBOOK_MAP[ctx.anomaly_type],
            action_plan=action_plan,
            applied_payload=applied,
            rollback_payload=rollback,
            finance_dashboard_data=finance,
            engineering_dashboard_data=engineering,
            correlation_id=request.correlation_id,
            dry_run_mode=request.dry_run_mode,
        )

    def verify(self, request: VerifyRequest) -> VerifyResponse:
        action_status = request.action_executed.status.value
        post_costs = request.post_telemetry_window.aws_cost_explorer_daily


        if action_status == "FAILED":
            return VerifyResponse(
                success=False,
                regression_detected=False,
                next_action=NextAction.ROLLBACK,
            )


        avg_post_cost = (
            sum(float(r.get("unblended_cost", 0)) for r in post_costs) / len(post_costs)
            if post_costs
            else 0.0
        )
        cost_normalized = avg_post_cost > 100.0


        outcome = random.choices(
            ["DONE", "RETRY", "ROLLBACK", "ESCALATE"],
            weights=[85, 10, 4, 1],
            k=1,
        )[0]

        if outcome == "DONE":
            return VerifyResponse(success=True, regression_detected=False, next_action=NextAction.DONE)

        if outcome == "RETRY":
            return VerifyResponse(success=False, regression_detected=False, next_action=NextAction.RETRY)

        if outcome == "ROLLBACK":
            return VerifyResponse(success=False, regression_detected=True, next_action=NextAction.ROLLBACK)


        now_iso = datetime.datetime.utcnow().isoformat() + "Z"
        target = request.action_executed.target
        return VerifyResponse(
            success=False,
            regression_detected=True,
            next_action=NextAction.ESCALATE,
            escalation_bundle=EscalationBundle(
                reason=(
                    f"After containment action on {target}, cost did not decrease "
                    "and resource owner did not acknowledge within the countdown window. "
                    "On-call engineer intervention required."
                ),
                logs=[
                    f"{now_iso} [WARN] containment applied but cost_ratio still elevated",
                    f"{now_iso} [WARN] No owner response within 4-hour window",
                ],
                metrics=EscalationMetrics(
                    unblended_cost_24h_usd=round(avg_post_cost, 2) if avg_post_cost else 427.50,
                    cost_ratio_to_7d_avg=round(random.uniform(10.0, 20.0), 1),
                    usage_density_24h=round(random.uniform(0.8, 1.0), 2),
                ),
            ),
        )

    def record_rollback(self, audit_id: str, request: RollbackRequest) -> RollbackResponse:
        tenant_key = "default"
        burned = _error_budget_store.get(tenant_key, 0.0)
        burned = round(burned + random.uniform(0.3, 1.5), 2)
        _error_budget_store[tenant_key] = burned

        prod_threshold = settings.error_budget_lock_threshold_prod
        locked = burned >= prod_threshold

        MockDetectService.update_status(
            audit_id,
            RemediationStatus.ROLLED_BACK,
            ActionLogEntry(
                timestamp=datetime.datetime.utcnow().isoformat() + "Z",
                action="tag-for-review",
                status="ROLLED_BACK",
                actor=request.rolled_back_by,
            ),
        )

        message = (
            f"Rollback recorded for {audit_id}. Reason: {request.reason}. "
            f"Error budget burned: {burned:.1f}%."
        )
        if locked:
            message += (
                f" Error budget exceeded {prod_threshold}%. "
                "Tenant switched to LOCKED_MODE — all containment actions will be dry-run only."
            )

        return RollbackResponse(
            rollback_recorded=True,
            false_positive_count_updated=True,
            new_error_budget_burned_pct=burned,
            containment_locked=locked,
            message=message,
        )
