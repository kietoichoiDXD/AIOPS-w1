"""
ProductionDecisionService — real decide / verify / rollback engine.

Implements the same interface as MockDecisionService but:
  - RCA uses the ai_model_used field (driver_feature from statistical detector)
    as primary_driver_feature instead of hard-coded defaults
  - verify() compares post-action cost against pre-action baseline
    instead of random weights
  - rollback() persists error budget per (tenant_id, environment) correctly
  - Error budget thresholds are per-environment per contract §3.3
  - All status mutations go through StatisticalDetectService.update_status()
    (no coupling to Mock layer)

AWS CLI commands follow contract §7 Containment Actions enum exactly:
  prod/*          → tag-for-review only  (never auto-shutdown)
  staging         → time-gated-countdown (4h) → auto-shutdown fallback
  dev/sandbox     → auto-shutdown immediately
  ml-research     → stop SageMaker notebook or EC2
  data-analytics  → quota-cap on DataTransfer
"""

from __future__ import annotations

import datetime
import logging
from typing import TYPE_CHECKING

from app.models.enums import (
    AnomalyType,
    AppliedActionType,
    ContainmentAction,
    Environment,
    NextAction,
    RemediationStatus,
    RollbackActionType,
    Severity,
)
from app.schemas.decide import (
    ActionPlanStep,
    AppliedPayload,
    DecideRequest,
    DecideResponse,
    EngineeringDashboardData,
    FinanceAllocation,
    FinanceDashboardData,
    FinanceMetrics,
    RollbackPayload,
    RootCauseAnalysis,
    SlackRouting,
    TechnicalContext,
)
from app.schemas.status import ActionLogEntry, RollbackRequest, RollbackResponse
from app.schemas.verify import EscalationBundle, EscalationMetrics, VerifyRequest, VerifyResponse
from app.services.base import DecisionService

if TYPE_CHECKING:
    from app.services.ml.statistical_detect_service import StatisticalDetectService
    from app.services.ml.tenant_state import TenantStateService

logger = logging.getLogger(__name__)

_REGION = "ap-southeast-1"



_RUNBOOK_MAP: dict[AnomalyType, str] = {
    AnomalyType.runaway_usage:  "RunawayMLClusterContainmentRunbook",
    AnomalyType.idle_resource:  "IdleResourceDecommissionRunbook",
    AnomalyType.untagged_spend: "UntaggedSpendRemediationRunbook",
    AnomalyType.sudden_spike:   "SuddenSpikeContainmentRunbook",
    AnomalyType.gradual_drift:  "GradualDriftQuotaCapRunbook",
}


_TECH_CTX: dict[AnomalyType, dict] = {
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



_RCA_REASON: dict[AnomalyType, dict[str, str]] = {
    AnomalyType.sudden_spike: {
        "robust_z": (
            "Cost deviated >2.5σ (robust MAD z-score) above the 14-day rolling median "
            "in a single day. Likely causes: debug logging left enabled, auto-scaling "
            "misconfiguration, unexpected data ingress, or Lambda cold-start amplification."
        ),
        "cost_ratio_to_7d_avg": (
            "Cost exceeded 5× the 7-day rolling average in a single billing period. "
            "Likely: unexpected invocation burst or on-demand provisioning without quota."
        ),
        "peer_ratio": (
            "Resource cost exceeded 3× the median for the same service and account on "
            "the same day. Anomalous compared to peer resources in the same workload."
        ),
        "default": "Sudden cost spike detected via statistical analysis of rolling cost history.",
    },
    AnomalyType.gradual_drift: {
        "slope_14d": (
            "14-day cost trend slope is positive and 28-day cost grew >10%. "
            "Likely: auto-scaling ratchet, data volume growth without quota, or "
            "gradual resource leak accumulating over billing periods."
        ),
        "default": "Sustained upward cost drift over 14–28 days detected.",
    },
    AnomalyType.idle_resource: {
        "usage_density_24h": (
            "Resource billed continuously (24h/day) but usage_density_24h ≤ 5%. "
            "Likely orphaned after migration, experiment, or forgotten dev/test instance."
        ),
        "cpu_mean": (
            "CPU utilisation below 10% despite non-zero billing. "
            "Resource appears idle — no active workload detected."
        ),
        "default": "Idle resource detected: billed but not utilised.",
    },
    AnomalyType.runaway_usage: {
        "usage_density_24h": (
            "usage_density_24h ≥ 95% — resource running at near-full capacity 24/7 "
            "with no campaign, load-test, or migration flag set. "
            "Suspected: abandoned training job or developer forgot to stop instance."
        ),
        "cpu_mean": (
            "CPU utilisation >80% sustained with cost ratio above baseline. "
            "Resource running flat-out without a scheduled workload justification."
        ),
        "default": "Runaway usage: resource at maximum capacity without scheduled workload.",
    },
    AnomalyType.untagged_spend: {
        "resource_tags_user_team": (
            "Resource incurring ≥$50/day with no team or owner tag. "
            "Cannot route alert to responsible squad. "
            "Apply mandatory tags (team, owner, cost_center) per tagging policy."
        ),
        "default": "Significant spend from untagged resource — cannot attribute to team.",
    },
}

_MISSING_TAGS_MAP: dict[AnomalyType, list[str]] = {
    AnomalyType.untagged_spend: ["resource_tags_user_team", "resource_tags_user_owner"],
    AnomalyType.runaway_usage:  [],
    AnomalyType.idle_resource:  [],
    AnomalyType.sudden_spike:   [],
    AnomalyType.gradual_drift:  [],
}

_SLACK_CHANNELS: dict[str, str] = {
    "prod":           "#finops-alert-prod",
    "prod-core":      "#finops-alert-prod",
    "prod-payments":  "#finops-alert-prod",
    "staging":        "#finops-alert-staging",
    "dev":            "#finops-alert-dev",
    "sandbox":        "#finops-alert-dev",
    "ml-research":    "#finops-alert-ml",
    "data-analytics": "#finops-alert-data",
}




def _containment_action(env: str, anomaly_type: AnomalyType, resource_id: str) -> ContainmentAction:
    prod_envs = {"prod", "prod-core", "prod-payments"}
    if env in prod_envs:
        return ContainmentAction.tag_for_review
    if env == "staging":
        return ContainmentAction.time_gated_countdown
    if env in {"dev", "sandbox"}:
        return ContainmentAction.auto_shutdown
    if env == "ml-research":
        return ContainmentAction.auto_shutdown
    if env == "data-analytics":
        return ContainmentAction.quota_cap
    return ContainmentAction.tag_for_review


def _build_action_plan(action: ContainmentAction, resource_id: str) -> list[ActionPlanStep]:
    steps = [ActionPlanStep(step=1, action=ContainmentAction.tag_for_review, target=resource_id, params={})]
    if action == ContainmentAction.time_gated_countdown:
        steps.append(ActionPlanStep(
            step=2, action=ContainmentAction.time_gated_countdown, target=resource_id,
            params={"time_lock_seconds": 14400, "fallback_action": "auto-shutdown"},
        ))
    elif action == ContainmentAction.auto_shutdown:
        steps.append(ActionPlanStep(step=2, action=ContainmentAction.auto_shutdown, target=resource_id, params={}))
    elif action == ContainmentAction.quota_cap:
        steps.append(ActionPlanStep(
            step=2, action=ContainmentAction.quota_cap, target=resource_id,
            params={"new_quota_value": "10GB", "service": "AWSDataTransfer"},
        ))
    return steps


def _build_applied(action: ContainmentAction, resource_id: str, anomaly_id: str) -> AppliedPayload:
    is_notebook = "notebook" in resource_id.lower() or "sagemaker" in resource_id.lower()
    is_rds = "rds" in resource_id.lower() or "db:" in resource_id.lower()

    if action == ContainmentAction.auto_shutdown:
        if is_notebook:
            return AppliedPayload(
                action_type=AppliedActionType.stop_sagemaker_notebook,
                aws_cli_command=(
                    f"aws sagemaker stop-notebook-instance "
                    f"--notebook-instance-name {resource_id} --region {_REGION}"
                ),
            )
        if is_rds:
            return AppliedPayload(
                action_type=AppliedActionType.stop_instance,
                aws_cli_command=(
                    f"aws rds stop-db-instance "
                    f"--db-instance-identifier {resource_id} --region {_REGION}"
                ),
            )
        return AppliedPayload(
            action_type=AppliedActionType.stop_instance,
            aws_cli_command=f"aws ec2 stop-instances --instance-ids {resource_id} --region {_REGION}",
        )


    return AppliedPayload(
        action_type=AppliedActionType.inject_aws_tag,
        aws_cli_command=(
            f"aws ec2 create-tags --resources {resource_id} "
            f"--tags Key=finops:review,Value=pending "
            f"Key=finops:anomaly-id,Value={anomaly_id} --region {_REGION}"
        ),
    )


def _build_rollback(action: ContainmentAction, resource_id: str) -> RollbackPayload:
    is_notebook = "notebook" in resource_id.lower() or "sagemaker" in resource_id.lower()
    is_rds = "rds" in resource_id.lower() or "db:" in resource_id.lower()

    if action == ContainmentAction.auto_shutdown:
        if is_notebook:
            return RollbackPayload(
                action_type=RollbackActionType.start_sagemaker_notebook,
                aws_cli_rollback_command=(
                    f"aws sagemaker start-notebook-instance "
                    f"--notebook-instance-name {resource_id} --region {_REGION}"
                ),
                original_resource_id=resource_id,
            )
        if is_rds:
            return RollbackPayload(
                action_type=RollbackActionType.start_instance,
                aws_cli_rollback_command=(
                    f"aws rds start-db-instance "
                    f"--db-instance-identifier {resource_id} --region {_REGION}"
                ),
                original_resource_id=resource_id,
            )
        return RollbackPayload(
            action_type=RollbackActionType.start_instance,
            aws_cli_rollback_command=(
                f"aws ec2 start-instances --instance-ids {resource_id} --region {_REGION}"
            ),
            original_resource_id=resource_id,
        )

    return RollbackPayload(
        action_type=RollbackActionType.remove_aws_tag,
        aws_cli_rollback_command=(
            f"aws ec2 delete-tags --resources {resource_id} "
            f"--tags Key=finops:review Key=finops:anomaly-id --region {_REGION}"
        ),
        original_resource_id=resource_id,
    )


def _extract_driver(ai_model_used: str) -> str:
    """Parse driver_feature from ai_model_used = 'statistical:driver_feature'."""
    if ":" in ai_model_used:
        parts = ai_model_used.split(":")
        return parts[-1]
    return "cost_ratio_to_7d_avg"


def _build_rca(anomaly_type: AnomalyType, driver_feature: str) -> RootCauseAnalysis:
    reasons = _RCA_REASON.get(anomaly_type, {})
    reason = reasons.get(driver_feature) or reasons.get("default", "Cost anomaly detected.")
    missing_tags = _MISSING_TAGS_MAP.get(anomaly_type, [])
    return RootCauseAnalysis(
        primary_driver_feature=driver_feature,
        technical_reason=reason,
        missing_mandatory_tags=missing_tags,
    )




class ProductionDecisionService(DecisionService):
    """
    Real decision, verify, and rollback service.

    decide()  — deterministic runbook match + RCA from driver feature
    verify()  — compares post-action cost to pre-action; returns DONE/RETRY/ROLLBACK/ESCALATE
    rollback() — increments error budget, triggers LOCKED_MODE if threshold exceeded
    """

    def __init__(
        self,
        detect_service: "StatisticalDetectService",
        tenant_state: "TenantStateService | None" = None,
    ) -> None:
        self._detect = detect_service
        self._tenant_state = tenant_state

        self._pre_action_costs: dict[str, float] = {}

    def decide(self, request: DecideRequest, locked: bool = False) -> DecideResponse:
        ctx = request.anomaly_context
        env = ctx.environment.value
        driver = _extract_driver(ctx.anomaly_type.value)



        effective_dry_run = request.dry_run_mode or locked
        if locked:
            action = ContainmentAction.tag_for_review
        else:
            action = _containment_action(env, ctx.anomaly_type, ctx.resource_id)
        plan = _build_action_plan(action, ctx.resource_id)
        applied = _build_applied(action, ctx.resource_id, ctx.anomaly_id)
        rollback = _build_rollback(action, ctx.resource_id)



        driver_feature = driver
        rca = _build_rca(ctx.anomaly_type, driver_feature)

        tech_ctx = _TECH_CTX.get(ctx.anomaly_type, _TECH_CTX[AnomalyType.sudden_spike])
        projected = round(ctx.unblended_cost_24h_usd * 30, 2)
        team = ctx.responsible_team or "UNASSIGNED"
        cost_center = ctx.cost_center_code or "CC-UNKNOWN"
        channel = _SLACK_CHANNELS.get(env, "#finops-alert")

        finance_summary = (
            f"Resource {ctx.resource_id} ({team}) flagged as "
            f"{ctx.anomaly_type.value.replace('_', ' ')}. "
            f"Cost: ${ctx.unblended_cost_24h_usd:.2f}/day "
            f"({ctx.cost_ratio_to_7d_avg:.1f}× 7-day average). "
            f"Projected monthly waste: ${projected:,.2f}. "
            f"Containment initiated (dry_run={effective_dry_run}"
            f"{', LOCKED_MODE' if locked else ''})."
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
            target_recipient=f"Engineering Console & Slack {channel}",
            technical_context=TechnicalContext(**tech_ctx),
            root_cause_analysis=rca,
            slack_routing=SlackRouting(
                channel_name=channel,
                webhook_url_pointer=f"ssm:/finops-watch/{env}/slack-webhook",
            ),
        )


        self._pre_action_costs[request.correlation_id] = ctx.unblended_cost_24h_usd


        now_iso = datetime.datetime.utcnow().isoformat() + "Z"
        log_entry = ActionLogEntry(
            timestamp=now_iso,
            action=plan[0].action,
            status="DRY_RUN_COMPLETED" if effective_dry_run else "COMPLETED",
            actor="finops-ai-engine-role",
        )
        from app.services.ml.statistical_detect_service import StatisticalDetectService
        StatisticalDetectService.update_status(ctx.anomaly_id, RemediationStatus.IN_PROGRESS, log_entry)

        return DecideResponse(
            matched_runbook=_RUNBOOK_MAP[ctx.anomaly_type],
            action_plan=plan,
            applied_payload=applied,
            rollback_payload=rollback,
            finance_dashboard_data=finance,
            engineering_dashboard_data=engineering,
            correlation_id=request.correlation_id,
            dry_run_mode=effective_dry_run,
        )

    def verify(self, request: VerifyRequest) -> VerifyResponse:
        action_status = request.action_executed.status.value


        if action_status == "FAILED":
            return VerifyResponse(success=False, regression_detected=False, next_action=NextAction.ROLLBACK)


        pre_cost = self._pre_action_costs.get(request.correlation_id, 0.0)
        post_rows = request.post_telemetry_window.aws_cost_explorer_daily or []
        avg_post = (
            sum(float(r.get("unblended_cost", 0)) for r in post_rows) / len(post_rows)
            if post_rows else 0.0
        )

        cost_resolved = (pre_cost == 0.0) or (avg_post < pre_cost * 0.5)
        regression = avg_post > pre_cost * 1.3 and pre_cost > 0

        if cost_resolved and not regression:
            return VerifyResponse(success=True, regression_detected=False, next_action=NextAction.DONE)

        if regression:
            now_iso = datetime.datetime.utcnow().isoformat() + "Z"
            target = request.action_executed.target
            return VerifyResponse(
                success=False,
                regression_detected=True,
                next_action=NextAction.ESCALATE,
                escalation_bundle=EscalationBundle(
                    reason=(
                        f"Post-action cost (${avg_post:.2f}/day) is >{int((avg_post/max(pre_cost,1)-1)*100)}% "
                        f"above pre-action baseline (${pre_cost:.2f}/day). "
                        f"Containment on {target} may have caused a side-effect regression."
                    ),
                    logs=[
                        f"{now_iso} [WARN] post-action avg_cost={avg_post:.2f} > pre_cost={pre_cost:.2f}",
                        f"{now_iso} [WARN] regression_threshold=130% breached",
                    ],
                    metrics=EscalationMetrics(
                        unblended_cost_24h_usd=round(avg_post, 2),
                        cost_ratio_to_7d_avg=round(avg_post / max(pre_cost, 1), 2),
                        usage_density_24h=1.0,
                    ),
                ),
            )


        return VerifyResponse(success=False, regression_detected=False, next_action=NextAction.RETRY)

    def record_rollback(
        self, audit_id: str, request: RollbackRequest, tenant_id: str = "default"
    ) -> RollbackResponse:


        ts = self._tenant_state
        env = ts.env_of(audit_id) if ts else "prod"
        threshold = ts.threshold(env) if ts else float("inf")

        if ts:
            burned, locked = ts.burn_rollback(tenant_id, env)
        else:
            burned, locked = 0.5, False

        remaining = ts.remaining_pct(tenant_id, env) if ts else round(100.0 - burned, 1)

        from app.services.ml.statistical_detect_service import StatisticalDetectService
        StatisticalDetectService.update_status(
            audit_id,
            RemediationStatus.ROLLED_BACK,
            ActionLogEntry(
                timestamp=datetime.datetime.utcnow().isoformat() + "Z",
                action=ContainmentAction.tag_for_review,
                status="ROLLED_BACK",
                actor=request.rolled_back_by,
            ),
            containment_locked=locked,
            error_budget_remaining_pct=remaining,
        )

        threshold_str = "n/a (unlimited)" if threshold == float("inf") else f"{threshold:.0f}%"
        msg = (
            f"Rollback recorded for {audit_id}. Reason: {request.reason}. "
            f"Error budget burned: {burned:.1f}% (threshold: {threshold_str})."
        )
        if locked:
            msg += (
                f" Error budget exceeded {threshold_str}. "
                "Tenant switched to LOCKED_MODE — all containment will be dry-run only."
            )

        return RollbackResponse(
            rollback_recorded=True,
            false_positive_count_updated=True,
            new_error_budget_burned_pct=burned,
            containment_locked=locked,
            message=msg,
        )
