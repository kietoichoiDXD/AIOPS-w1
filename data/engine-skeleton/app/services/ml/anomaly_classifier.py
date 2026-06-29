"""
anomaly_classifier.py — Map XGBoost 3-class output + feature values to AnomalyType, Severity,
and alert routing per the contract enum reference (§6, §7 of ai-api-contract.md v1.4.0).

Label encoding (from FEATURE_v2 / LABEL_MAP):
  0 = normal
  1 = anomaly   ← what we alert on
  2 = benign    ← cost spike with known business justification (migration_flag, campaign_flag)
"""

from __future__ import annotations

import datetime
import random
import string

import numpy as np
import pandas as pd

from app.models.enums import AnomalyType, Severity
from app.schemas.detect import AlertRouting, AnomalyItem




def _is_business_justified(business_context: dict | None) -> bool:
    if not business_context:
        return False
    return any([
        business_context.get("campaign_flag", False),
        business_context.get("load_test_flag", False),
        business_context.get("migration_flag", False),
    ])




def _infer_anomaly_type(row: pd.Series) -> AnomalyType:
    """
    Rule-based type classification on top of the binary anomaly decision.
    Priority order matches operational likelihood (contract §6).
    """
    cost = float(row.get("line_item_unblended_cost", 0))
    ratio = float(row.get("cost_ratio_to_7d_avg", 1))
    team_missing = bool(row.get("team_missing", 0))
    owner_missing = bool(row.get("owner_missing", 0))
    cpu_mean = float(row.get("cpu_mean", 50))
    spike = float(row.get("absolute_cost_spike", 0))
    slope = float(row.get("slope_14d", 0))
    age = float(row.get("age_days", 1))


    if team_missing and owner_missing and cost > 50:
        return AnomalyType.untagged_spend


    if cpu_mean > 80 and ratio > 3 and cost > 100:
        return AnomalyType.runaway_usage


    if cpu_mean < 5 and age > 3 and cost > 20:
        return AnomalyType.idle_resource


    if spike > 0 or ratio > 5:
        return AnomalyType.sudden_spike


    if slope > 0:
        return AnomalyType.gradual_drift

    return AnomalyType.sudden_spike


def _infer_severity(
    anomaly_type: AnomalyType,
    cost: float,
    ratio: float,
    confidence: float,
) -> Severity:
    if anomaly_type == AnomalyType.runaway_usage:
        return Severity.HIGH if cost > 200 else Severity.MEDIUM
    if anomaly_type == AnomalyType.sudden_spike:
        return Severity.HIGH if ratio > 8 else Severity.MEDIUM
    if anomaly_type == AnomalyType.idle_resource:
        return Severity.MEDIUM if cost > 100 else Severity.LOW
    if anomaly_type == AnomalyType.untagged_spend:
        return Severity.MEDIUM
    if anomaly_type == AnomalyType.gradual_drift:
        return Severity.LOW
    return Severity.MEDIUM


def _make_anomaly_id() -> str:
    today = datetime.date.today()
    letter = random.choice(string.ascii_uppercase)
    return f"ANM-{today.year}-{today.month:02d}{today.day:02d}{letter}"


def _alert_routing(anomaly_type: AnomalyType, cost: float, ratio: float) -> AlertRouting:
    finance = cost > 200 or ratio > 5.0
    engineering = anomaly_type in (
        AnomalyType.runaway_usage,
        AnomalyType.idle_resource,
        AnomalyType.sudden_spike,
    )
    return AlertRouting(finance=finance, engineering=engineering)




def build_anomaly_items(
    df: pd.DataFrame,
    probabilities: np.ndarray,
    threshold: float,
    telemetry_delay: bool = False,
    business_context: dict | None = None,
    model_name: str = "xgboost-v2-finops",
) -> list[AnomalyItem]:
    """
    Convert XGBoost probability outputs + raw feature rows into AnomalyItem list.

    Args:
        df            : full feature DataFrame (one row per CUR item)
        probabilities : shape (n, 3) — predict_proba output [normal, anomaly, benign]
        threshold     : decision threshold for class-1 (anomaly)
        telemetry_delay: lowers confidence by 0.08 per contract §3.1
        business_context: campaign/migration/load-test flags
        model_name    : logged in ai_model_used field

    Returns:
        List of AnomalyItem (may be empty)
    """
    anomaly_prob = probabilities[:, 1]
    results: list[AnomalyItem] = []
    seen_resources: set[str] = set()

    for i, prob in enumerate(anomaly_prob):
        if prob < threshold:
            continue

        row = df.iloc[i]
        resource_id = str(row.get("line_item_resource_id", f"unknown-{i}"))


        if resource_id in seen_resources:
            continue
        seen_resources.add(resource_id)


        benign_prob = probabilities[i, 2]
        if benign_prob > prob and _is_business_justified(business_context):
            continue

        cost = float(row.get("line_item_unblended_cost", 0))
        ratio = float(row.get("cost_ratio_to_7d_avg", 1.0))

        anomaly_type = _infer_anomaly_type(row)
        confidence = float(prob)
        if telemetry_delay:
            confidence = max(0.50, confidence - 0.08)

        severity = _infer_severity(anomaly_type, cost, ratio, confidence)
        routing = _alert_routing(anomaly_type, cost, ratio)
        environment = str(row.get("resource_tags_user_environment", "dev"))
        team = row.get("resource_tags_user_team")

        results.append(AnomalyItem(
            anomaly_id=_make_anomaly_id(),
            anomaly_type=anomaly_type,
            severity=severity,
            confidence_score=round(confidence, 4),
            resource_id=resource_id,
            environment=environment,
            responsible_team=team if team and str(team) != "nan" else None,
            unblended_cost_24h_usd=round(cost, 2),
            cost_ratio_to_7d_avg=round(ratio, 2),
            ai_model_used=model_name,
            alert_routing=routing,
        ))

    return results
