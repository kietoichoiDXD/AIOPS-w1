"""
Domain enumerations for the FinOps Watch AI Engine.
Centralised here so every module speaks the same vocabulary.
Easy to extend when curveballs add new anomaly types or actions.
"""

from enum import Enum


class AnomalyType(str, Enum):
    """Categories of cost anomalies the engine can detect.
    Aligned with TF2 dataset anomaly_labels_public.csv types.
    """
    RUNAWAY_USAGE = "runaway_usage"          # Compute quên tắt, chạy 24/7 (was: runaway_training)
    IDLE_RESOURCE = "idle_resource"          # Provisioned nhưng ~0 usage, kéo dài
    UNTAGGED_SPEND = "untagged_spend"        # Thiếu tag team → không phân bổ được (was: mis_tagged_spend)
    SUDDEN_SPIKE = "sudden_spike"            # Tăng vọt ngắn ngày do misconfig (was: spike_unknown)
    GRADUAL_DRIFT = "gradual_drift"          # Bò lên từ từ nhiều tuần, auto-scale không scale-down
    OVER_PROVISIONED = "over_provisioned"    # Instance quá lớn so với nhu cầu
    # -- Extend here for curveball new types --
    OTHER = "other"


class AlertRoute(str, Enum):
    """Who should receive the alert."""
    FINANCE = "finance"
    ENGINEERING = "engineering"
    BOTH = "both"


class SuggestedAction(str, Enum):
    """Safe actions the engine can recommend."""
    ALERT_ONLY = "alert_only"
    TAG_FOR_REVIEW = "tag_for_review"
    SCHEDULE_SHUTDOWN = "schedule_shutdown"
    QUOTA_CAP = "quota_cap"
    INVESTIGATE = "investigate"
    # -- Extend here for curveball --


class Environment(str, Enum):
    """Resource environment classification."""
    PROD = "prod"
    STAGING = "staging"
    DEV = "dev"
    SANDBOX = "sandbox"
    UNKNOWN = "unknown"


class ContainmentStatus(str, Enum):
    """Status of a containment action."""
    DRY_RUN = "dry_run"
    EXECUTED = "executed"
    SKIPPED_PROD = "skipped_prod"
    ESCALATED = "escalated"
    FAILED = "failed"
