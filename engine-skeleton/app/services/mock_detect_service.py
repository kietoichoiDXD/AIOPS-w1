"""
Mock implementation of DetectService.

Generates realistic-looking anomalies from the incoming telemetry.
Replace this class with a real Isolation Forest implementation without
touching any router or schema code.
"""

import datetime
import random
import string
import uuid
from typing import Any

from app.config.settings import settings
from app.models.enums import AnomalyType, RemediationStatus, Severity
from app.schemas.detect import AlertRouting, AnomalyItem, DetectRequest, DetectResponse
from app.schemas.status import ActionLogEntry, RemediationStatusResponse
from app.services.base import DetectService




_EC2_INSTANCES = [
    "i-0a1b2c3d4e5f67890",
    "i-0b2c3d4e5f6789012",
    "i-0c3d4e5f678901234",
    "i-0d4e5f67890123456",
    "i-0e5f6789012345678",
]

_SAGEMAKER_NOTEBOOKS = [
    "ml-notebook-gpu-training-01",
    "ml-notebook-bert-finetune",
    "ml-notebook-xgboost-research",
]

_RDS_INSTANCES = [
    "arn:aws:rds:ap-southeast-1:200000000010:db:db-prod-core-01",
    "arn:aws:rds:ap-southeast-1:200000000020:db:db-staging-orphan-01",
    "arn:aws:rds:ap-southeast-1:200000000030:db:db-dev-test",
]

_UNTAGGED_RESOURCES = [
    "i-0untaggedfleet01",
    "i-0untaggedfleet02",
    "arn:aws:s3:::untagged-data-lake-backup",
]

_LOG_GROUPS = [
    "arn:aws:logs:ap-southeast-1:200000000030:log-group:/aws/lambda/debug-hot-path",
    "arn:aws:logs:ap-southeast-1:200000000020:log-group:/aws/lambda/payment-processor",
]

_ENVIRONMENTS = {
    AnomalyType.runaway_usage: "ml-research",
    AnomalyType.idle_resource: "staging",
    AnomalyType.untagged_spend: "prod-payments",
    AnomalyType.sudden_spike: "dev",
    AnomalyType.gradual_drift: "data-analytics",
}

_TEAMS = {
    AnomalyType.runaway_usage: "squad-ml-core",
    AnomalyType.idle_resource: None,
    AnomalyType.untagged_spend: None,
    AnomalyType.sudden_spike: "squad-backend",
    AnomalyType.gradual_drift: "squad-data",
}

_SEVERITY_MAP = {
    AnomalyType.runaway_usage: Severity.HIGH,
    AnomalyType.idle_resource: Severity.MEDIUM,
    AnomalyType.untagged_spend: Severity.MEDIUM,
    AnomalyType.sudden_spike: Severity.HIGH,
    AnomalyType.gradual_drift: Severity.LOW,
}

_RCA_TEMPLATES: dict[AnomalyType, str] = {
    AnomalyType.runaway_usage: (
        "GPU/CPU instance running at full capacity (usage_density_24h ≥ 0.95) "
        "for more than 24 hours with no scheduled workload detected."
    ),
    AnomalyType.idle_resource: (
        "Resource has been provisioned for >3 days with near-zero utilization "
        "(usage_density_24h ≤ 0.05). Likely orphaned after a migration or experiment."
    ),
    AnomalyType.untagged_spend: (
        "Resource incurring significant cost ($>{cost:.0f}/day) has no "
        "resource_tags_user_team tag. Cannot route alert to an owner."
    ),
    AnomalyType.sudden_spike: (
        "Cost spiked {ratio:.1f}× above 7-day average in a single day. "
        "Possible causes: debug logging left enabled, auto-scaling misconfiguration, "
        "or unexpected data ingress."
    ),
    AnomalyType.gradual_drift: (
        "Cost trend increasing >5%/week for the past 4 weeks. "
        "Likely caused by auto-scaling ratchet or data growth without quota enforcement."
    ),
}


def _make_anomaly_id() -> str:
    today = datetime.date.today()
    letter = random.choice(string.ascii_uppercase)
    return f"ANM-{today.year}-{today.month:02d}{today.day:02d}{letter}"


def _resource_for_type(anomaly_type: AnomalyType) -> str:
    if anomaly_type == AnomalyType.runaway_usage:
        return random.choice(_EC2_INSTANCES + _SAGEMAKER_NOTEBOOKS)
    if anomaly_type == AnomalyType.idle_resource:
        return random.choice(_RDS_INSTANCES)
    if anomaly_type == AnomalyType.untagged_spend:
        return random.choice(_UNTAGGED_RESOURCES)
    if anomaly_type == AnomalyType.sudden_spike:
        return random.choice(_LOG_GROUPS)
    return random.choice(_EC2_INSTANCES)


def _pick_anomaly_types(max_count: int) -> list[AnomalyType]:
    """Weighted random selection of anomaly types without repetition."""
    weights = [0.30, 0.25, 0.20, 0.15, 0.10]
    types = list(AnomalyType)
    selected: list[AnomalyType] = []
    available = list(range(len(types)))
    for _ in range(min(max_count, len(types))):
        w = [weights[i] for i in available]
        total = sum(w)
        norm = [x / total for x in w]
        idx = random.choices(available, weights=norm, k=1)[0]
        selected.append(types[idx])
        available.remove(idx)
    return selected


def _build_anomaly(anomaly_type: AnomalyType, ce_items: list[Any], telemetry_delay: bool) -> AnomalyItem:
    resource_id = _resource_for_type(anomaly_type)
    cost = round(random.uniform(50.0, 1500.0), 2)
    ratio = round(random.uniform(3.5, 22.0), 1)

    confidence_base = {
        AnomalyType.runaway_usage: 0.90,
        AnomalyType.idle_resource: 0.85,
        AnomalyType.untagged_spend: 0.80,
        AnomalyType.sudden_spike: 0.92,
        AnomalyType.gradual_drift: 0.72,
    }[anomaly_type]

    if telemetry_delay:
        confidence_base -= 0.08

    confidence = round(min(0.99, max(0.55, confidence_base + random.uniform(-0.05, 0.05))), 2)

    finance_alert = cost > 200 or ratio > 5.0
    severity = _SEVERITY_MAP[anomaly_type]

    return AnomalyItem(
        anomaly_id=_make_anomaly_id(),
        anomaly_type=anomaly_type,
        severity=severity,
        confidence_score=confidence,
        resource_id=resource_id,
        environment=_ENVIRONMENTS[anomaly_type],
        responsible_team=_TEAMS[anomaly_type],
        unblended_cost_24h_usd=cost,
        cost_ratio_to_7d_avg=ratio,
        ai_model_used="mock-isolation-forest-v1",
        alert_routing=AlertRouting(finance=finance_alert, engineering=True),
    )




_status_store: dict[str, RemediationStatusResponse] = {}


class MockDetectService(DetectService):
    """
    Mock anomaly detection service.

    Behaviour is driven by:
      - settings.mock_anomaly_probability  — probability of finding anomalies
      - settings.mock_max_anomalies        — ceiling on anomalies returned

    When telemetry_delay_event=True, confidence scores are reduced by 8 points.
    """

    def detect(self, request: DetectRequest, correlation_id: str) -> DetectResponse:
        if random.random() > settings.mock_anomaly_probability:
            return DetectResponse(
                success=True,
                correlation_id=correlation_id,
                anomalies_detected=False,
                anomalies_list=[],
            )

        count = random.randint(1, settings.mock_max_anomalies)
        anomaly_types = _pick_anomaly_types(count)

        anomalies: list[AnomalyItem] = []
        for atype in anomaly_types:
            anomaly = _build_anomaly(atype, request.aws_cost_explorer_daily, request.telemetry_delay_event)
            anomalies.append(anomaly)


            _status_store[anomaly.anomaly_id] = RemediationStatusResponse(
                audit_id=str(uuid.uuid4()),
                anomaly_id=anomaly.anomaly_id,
                status=RemediationStatus.PENDING_APPROVAL,
                containment_locked=False,
                error_budget_remaining_pct=round(random.uniform(85.0, 100.0), 1),
                actions_log=[],
            )

        return DetectResponse(
            success=True,
            correlation_id=correlation_id,
            anomalies_detected=True,
            anomalies_list=anomalies,
        )

    def get_status(self, anomaly_id: str) -> RemediationStatusResponse | None:
        return _status_store.get(anomaly_id)

    @staticmethod
    def update_status(anomaly_id: str, status: RemediationStatus, log_entry: ActionLogEntry) -> None:
        """Called by decision service to keep status consistent."""
        record = _status_store.get(anomaly_id)
        if record:
            record.status = status
            record.actions_log.append(log_entry)
