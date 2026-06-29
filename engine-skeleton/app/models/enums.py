from enum import Enum


class AnomalyType(str, Enum):
    runaway_usage = "runaway_usage"
    idle_resource = "idle_resource"
    untagged_spend = "untagged_spend"
    sudden_spike = "sudden_spike"
    gradual_drift = "gradual_drift"


class Severity(str, Enum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class ContainmentAction(str, Enum):
    tag_for_review = "tag-for-review"
    time_gated_countdown = "time-gated-countdown"
    auto_shutdown = "auto-shutdown"
    quota_cap = "quota-cap"


class AppliedActionType(str, Enum):
    inject_aws_tag = "inject_aws_tag"
    stop_instance = "stop_instance"
    stop_sagemaker_notebook = "stop_sagemaker_notebook"
    restrict_quota = "restrict_quota"


class RollbackActionType(str, Enum):
    remove_aws_tag = "remove_aws_tag"
    start_instance = "start_instance"
    start_sagemaker_notebook = "start_sagemaker_notebook"
    restore_quota = "restore_quota"


class Environment(str, Enum):
    prod = "prod"
    prod_core = "prod-core"
    prod_payments = "prod-payments"
    staging = "staging"
    dev = "dev"
    sandbox = "sandbox"
    ml_research = "ml-research"
    data_analytics = "data-analytics"


class DataSourceType(str, Enum):
    RAW_JSON = "RAW_JSON"
    S3_POINTER = "S3_POINTER"


class DataConfidence(str, Enum):
    """Detect response confidence in the underlying telemetry (contract §5.1)."""
    HIGH = "HIGH"
    LOW = "LOW"


class TrafficSource(str, Enum):
    ALB = "ALB"
    CloudFront = "CloudFront"
    ApiGateway = "ApiGateway"
    Synthetic = "Synthetic"
    Mixed = "Mixed"


class RemediationStatus(str, Enum):
    PENDING_APPROVAL = "PENDING_APPROVAL"
    IN_PROGRESS = "IN_PROGRESS"
    SUCCESS = "SUCCESS"
    ROLLED_BACK = "ROLLED_BACK"
    ESCALATED = "ESCALATED"


class NextAction(str, Enum):
    DONE = "DONE"
    RETRY = "RETRY"
    ROLLBACK = "ROLLBACK"
    ESCALATE = "ESCALATE"


class ActionExecutionStatus(str, Enum):
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class HealthStatus(str, Enum):
    healthy = "healthy"
    degraded = "degraded"
    unhealthy = "unhealthy"
