"""
XGBoost-based real detection service.

Replaces MockDetectService. Pipeline:
  1. build_feature_dataframe()  — FEATURE_v2 feature engineering on CUR payload
  2. XGBoost predict_proba()    — 3-class: normal(0) / anomaly(1) / benign(2)
  3. threshold (default 0.40)   — optimised from walk-forward CV in DETECT_v2
  4. rule-based anomaly typing  — maps each flagged row to one of 5 AnomalyTypes
  5. SHAP top-feature           — primary_driver_feature for /v1/decide RCA

Model loading strategy:
  - MLFLOW_TRACKING_URI env var set → load latest Production model from MLflow
  - DATA_DIR env var set → load model.ubj from local mlruns directory
  - Otherwise → warn and fall back to RuleBasedFallback (never raises 500)
"""

from __future__ import annotations

import datetime
import logging
import os
import random
import string
import uuid
import warnings
from typing import Any

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")
logger = logging.getLogger(__name__)

from app.models.enums import AnomalyType, RemediationStatus, Severity
from app.schemas.detect import AlertRouting, AnomalyItem, DetectRequest, DetectResponse
from app.schemas.status import ActionLogEntry, RemediationStatusResponse
from app.services.base import DetectService
from app.services.ml.feature_builder import FEATURE_COLS_V2, build_feature_dataframe



_status_store: dict[str, RemediationStatusResponse] = {}



DEFAULT_ANOMALY_THRESHOLD = 0.40




def _classify_anomaly_type(row: pd.Series) -> AnomalyType:
    """
    Map a flagged CUR row to one of 5 anomaly types using domain rules.
    Priority order matches operational likelihood from mock_detect_service weights.
    """
    team_missing = bool(row.get("team_missing", 0))
    owner_missing = bool(row.get("owner_missing", 0))
    cost_ratio = float(row.get("cost_ratio_to_7d_avg", 1.0))
    robust_z = float(row.get("robust_z", 0.0))
    absolute_spike = float(row.get("absolute_cost_spike", 0.0))
    slope = float(row.get("slope_14d", 0.0))
    cpu_mean = float(row.get("cpu_mean", 50.0))
    pct_change_28d = float(row.get("cost_pct_change_28d", 0.0))


    if team_missing and owner_missing:
        return AnomalyType.untagged_spend


    if cost_ratio > 5.0 or (absolute_spike > 0 and robust_z > 3.0):
        return AnomalyType.sudden_spike


    if cost_ratio > 2.5 and cpu_mean > 70:
        return AnomalyType.runaway_usage


    if cpu_mean < 10 and cost_ratio < 1.5:
        return AnomalyType.idle_resource


    if pct_change_28d > 0.10 or slope > 0:
        return AnomalyType.gradual_drift


    return AnomalyType.runaway_usage


def _severity(anomaly_type: AnomalyType, cost: float, ratio: float) -> Severity:
    if anomaly_type in (AnomalyType.runaway_usage, AnomalyType.sudden_spike):
        return Severity.HIGH
    if cost > 500 or ratio > 10:
        return Severity.HIGH
    if anomaly_type == AnomalyType.gradual_drift:
        return Severity.LOW
    return Severity.MEDIUM


def _make_anomaly_id() -> str:
    today = datetime.date.today()
    letter = random.choice(string.ascii_uppercase)
    return f"ANM-{today.year}-{today.month:02d}{today.day:02d}{letter}"




def _load_model() -> Any | None:
    """
    Try to load XGBoost model in priority order:
      1. MLflow Model Registry (MLFLOW_TRACKING_URI env)
      2. Local mlruns directory (DATA_DIR env → search for latest model.ubj)
    Returns None if unavailable — caller falls back to rule-based detection.
    """

    mlflow_uri = os.getenv("MLFLOW_TRACKING_URI")
    if mlflow_uri:
        try:
            import mlflow.xgboost
            import mlflow
            mlflow.set_tracking_uri(mlflow_uri)
            client = mlflow.MlflowClient()

            for model_name in [
                "AWS_Cost_Anomaly_Detection_v2_Features",
                "AWS_Cost_Anomaly_Detection_LeakFree",
            ]:
                try:
                    versions = client.get_latest_versions(model_name, stages=["Production", "Staging", "None"])
                    if versions:
                        uri = f"models:/{model_name}/{versions[0].version}"
                        model = mlflow.xgboost.load_model(uri)
                        logger.info("Loaded XGBoost model from MLflow: %s v%s", model_name, versions[0].version)
                        return model
                except Exception:
                    continue
        except Exception as e:
            logger.warning("MLflow load failed: %s", e)


    data_dir = os.getenv("DATA_DIR", "")
    if data_dir:
        import glob
        ubj_files = sorted(glob.glob(os.path.join(data_dir, "mlruns", "**", "model.ubj"), recursive=True))
        if ubj_files:
            try:
                from xgboost import XGBClassifier
                model = XGBClassifier()
                model.load_model(ubj_files[-1])
                logger.info("Loaded XGBoost model from: %s", ubj_files[-1])
                return model
            except Exception as e:
                logger.warning("Local model load failed: %s", e)

    logger.warning("No model found. Using rule-based fallback detection.")
    return None


def _load_shap_explainer(model: Any) -> Any | None:
    try:
        import shap
        return shap.TreeExplainer(model)
    except Exception:
        return None




def _top_shap_feature(
    explainer: Any | None,
    X_row: pd.DataFrame,
    class_idx: int = 1,
) -> str:
    """Return the feature with the highest |SHAP| value for anomaly class."""
    if explainer is None or X_row.empty:
        return "cost_ratio_to_7d_avg"
    try:
        import numpy as np
        sv = np.array(explainer.shap_values(X_row))
        if sv.ndim == 3:
            sv_anomaly = sv[0, :, class_idx]
        elif isinstance(explainer.shap_values(X_row), list):
            sv_anomaly = np.array(explainer.shap_values(X_row)[class_idx])[0]
        else:
            sv_anomaly = sv[0]
        top_idx = int(np.argabs(sv_anomaly).argmax()) if hasattr(np, "argabs") else int(np.abs(sv_anomaly).argmax())
        return X_row.columns[top_idx]
    except Exception:
        return "cost_ratio_to_7d_avg"


def _rule_based_detect(df_full: pd.DataFrame) -> np.ndarray:
    """
    Fallback when no model is loaded.
    Returns binary array (1 = anomaly) based on cost_ratio + robust_z thresholds.
    """
    ratio = df_full.get("cost_ratio_to_7d_avg", pd.Series([1.0] * len(df_full))).fillna(1.0)
    z = df_full.get("robust_z", pd.Series([0.0] * len(df_full))).fillna(0.0)
    spike = df_full.get("absolute_cost_spike", pd.Series([0.0] * len(df_full))).fillna(0.0)
    team_miss = df_full.get("team_missing", pd.Series([0] * len(df_full))).fillna(0)

    flagged = (
        (ratio > 5.0) |
        (z > 3.0) |
        (spike > 0) |
        ((ratio > 2.0) & (team_miss == 1))
    ).astype(int)
    return flagged.values




class XGBoostDetectService(DetectService):
    """
    Production anomaly detection service using XGBoost v2 feature set.

    Drop-in replacement for MockDetectService — same interface, same router.
    """

    def __init__(self, threshold: float = DEFAULT_ANOMALY_THRESHOLD) -> None:
        self._model = _load_model()
        self._threshold = threshold
        self._explainer = _load_shap_explainer(self._model) if self._model else None
        self._using_fallback = self._model is None



    def detect(self, request: DetectRequest, correlation_id: str) -> DetectResponse:
        cur_items = request.aws_cur_line_items or []


        if not cur_items:
            return DetectResponse(
                success=True,
                correlation_id=correlation_id,
                anomalies_detected=False,
                anomalies_list=[],
            )


        X, df_full = build_feature_dataframe(
            cur_items,
            metrics=request.resource_utilization_metrics,
        )


        if self._model is not None:
            try:
                proba_all = self._model.predict_proba(X)
                anomaly_prob = proba_all[:, 1]
                flagged_mask = anomaly_prob >= self._threshold
            except Exception as e:
                logger.error("Model scoring failed: %s — using fallback", e)
                flagged_mask = _rule_based_detect(df_full).astype(bool)
                anomaly_prob = flagged_mask.astype(float) * 0.75
        else:
            flagged_raw = _rule_based_detect(df_full)
            flagged_mask = flagged_raw.astype(bool)
            anomaly_prob = flagged_raw.astype(float) * 0.75


        confidence_penalty = 0.08 if request.telemetry_delay_event else 0.0


        anomalies: list[AnomalyItem] = []
        used_ids: set[str] = set()

        flagged_indices = np.where(flagged_mask)[0]
        for idx in flagged_indices:
            row = df_full.iloc[idx]
            cur = cur_items[idx]

            anomaly_type = _classify_anomaly_type(row)
            cost = float(row.get("line_item_unblended_cost", 0))
            ratio = float(row.get("cost_ratio_to_7d_avg", 1.0))
            prob = float(anomaly_prob[idx])
            confidence = round(max(0.50, min(0.99, prob - confidence_penalty)), 2)


            anomaly_id = _make_anomaly_id()
            while anomaly_id in used_ids:
                anomaly_id = _make_anomaly_id()
            used_ids.add(anomaly_id)


            top_feat = _top_shap_feature(self._explainer, X.iloc[[idx]])

            severity = _severity(anomaly_type, cost, ratio)
            finance_alert = cost > 200 or ratio > 5.0

            model_tag = (
                f"xgboost-v2:{top_feat}"
                if not self._using_fallback
                else f"rule-based:{top_feat}"
            )

            anomaly = AnomalyItem(
                anomaly_id=anomaly_id,
                anomaly_type=anomaly_type,
                severity=severity,
                confidence_score=confidence,
                resource_id=cur.line_item_resource_id,
                environment=getattr(cur, "resource_tags_user_environment", "dev"),
                responsible_team=cur.resource_tags_user_team,
                unblended_cost_24h_usd=round(cost, 2),
                cost_ratio_to_7d_avg=round(ratio, 2),
                ai_model_used=model_tag,
                alert_routing=AlertRouting(finance=finance_alert, engineering=True),
            )
            anomalies.append(anomaly)


            _status_store[anomaly_id] = RemediationStatusResponse(
                audit_id=str(uuid.uuid4()),
                anomaly_id=anomaly_id,
                status=RemediationStatus.PENDING_APPROVAL,
                containment_locked=False,
                error_budget_remaining_pct=100.0,
                actions_log=[],
            )

        return DetectResponse(
            success=True,
            correlation_id=correlation_id,
            anomalies_detected=len(anomalies) > 0,
            anomalies_list=anomalies,
        )

    def get_status(self, anomaly_id: str) -> RemediationStatusResponse | None:
        return _status_store.get(anomaly_id)

    @staticmethod
    def update_status(
        anomaly_id: str,
        status: RemediationStatus,
        log_entry: ActionLogEntry,
    ) -> None:
        record = _status_store.get(anomaly_id)
        if record:
            record.status = status
            record.actions_log.append(log_entry)
