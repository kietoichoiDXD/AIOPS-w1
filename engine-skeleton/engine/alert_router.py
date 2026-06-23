"""
Alert routing logic.
====================
Determines whether an anomaly alert should go to Finance, Engineering, or both.
Based on anomaly type, severity, and affected resource characteristics.
"""

from __future__ import annotations

from models.domain import AnomalyResult
from models.enums import AlertRoute, AnomalyType


def determine_alert_route(result: AnomalyResult) -> AlertRoute:
    """
    Route alerts based on anomaly characteristics.

    Rules:
    - Runaway training / idle resource → Engineering (operational issue)
    - Mis-tagged spend → Both (Finance cares about allocation, Eng fixes tags)
    - High severity (>= 0.7) → Both (everyone needs to know)
    - Otherwise → Finance (cost impact only)
    """
    if not result.is_anomaly:
        return AlertRoute.FINANCE  # Normal spend updates go to Finance dashboard

    # High severity → always both
    if result.severity >= 0.7:
        return AlertRoute.BOTH

    # Route by anomaly type
    routing_map = {
        AnomalyType.RUNAWAY_USAGE: AlertRoute.ENGINEERING,
        AnomalyType.IDLE_RESOURCE: AlertRoute.ENGINEERING,
        AnomalyType.UNTAGGED_SPEND: AlertRoute.BOTH,
        AnomalyType.SUDDEN_SPIKE: AlertRoute.BOTH,
        AnomalyType.GRADUAL_DRIFT: AlertRoute.BOTH,
        AnomalyType.OVER_PROVISIONED: AlertRoute.ENGINEERING,
        AnomalyType.OTHER: AlertRoute.FINANCE,
    }

    return routing_map.get(result.anomaly_type, AlertRoute.BOTH)


def generate_finance_summary(result: AnomalyResult) -> str:
    """Generate a Finance-friendly summary (no technical jargon)."""
    if not result.is_anomaly:
        return f"Spend is within normal range. Current: ${result.current_cost_usd or 0:.2f}/day."

    delta = result.cost_delta_usd or 0
    pct = result.cost_delta_pct or 0
    return (
        f"Cost alert: spending ${result.current_cost_usd or 0:.2f}/day, "
        f"which is ${delta:.2f} ({pct:.0f}%) above the baseline of "
        f"${result.baseline_cost_usd or 0:.2f}/day. "
        f"Recommended action: {result.anomaly_type.value.replace('_', ' ')}."
    )[:300]


def generate_engineering_summary(result: AnomalyResult) -> str:
    """Generate an Engineering-focused summary with actionable detail."""
    if not result.is_anomaly:
        return "No anomaly detected. All services operating within expected cost envelope."

    parts = [
        f"Anomaly: {result.anomaly_type.value}",
    ]
    if result.affected_account:
        account_label = result.affected_account
        if result.affected_account_name:
            account_label = f"{result.affected_account} ({result.affected_account_name})"
        parts.append(f"Account: {account_label}")
    if result.affected_service:
        parts.append(f"Service: {result.affected_service}")
    if result.affected_resource_id:
        parts.append(f"Resource: {result.affected_resource_id}")
    parts.append(f"Severity: {result.severity:.2f}")
    parts.append(f"Confidence: {result.confidence:.2f}")
    if result.cost_delta_usd:
        parts.append(f"Delta: +${result.cost_delta_usd:.2f}/day")

    return " | ".join(parts)[:300]
