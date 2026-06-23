"""
API Router — all endpoint definitions.
=======================================
Endpoints:
  GET  /health              → Health check (Deployment Contract §Health check)
  POST /v1/finops/detect    → FinOps anomaly detection (AI API Contract §Endpoint 1)
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Request, HTTPException

from api.schemas.detect import (
    ContainmentDetail,
    DetectRequest,
    DetectResponse,
    HealthResponse,
)
from config.settings import get_settings
from engine.alert_router import (
    determine_alert_route,
    generate_engineering_summary,
    generate_finance_summary,
)
from engine.audit import audit_logger
from engine.containment import evaluate_containment
from engine.strategies.base import DetectionStrategy
from engine.strategies.dummy import DummyStrategy
from engine.strategies.statistical import StatisticalStrategy

logger = logging.getLogger("finops-engine.router")

api_router = APIRouter()


# ---------------------------------------------------------------------------
# Strategy selection (feature-flag driven)
# ---------------------------------------------------------------------------
def _get_strategy() -> DetectionStrategy:
    """
    Select detection strategy based on configuration.
    Skeleton phase: DummyStrategy.
    W12: switch to StatisticalStrategy via env var FINOPS_ENABLE_LLM_ANALYSIS.
    """
    settings = get_settings()
    if settings.enable_llm_analysis:
        # W12: return LLM-enhanced strategy here
        return StatisticalStrategy()
    return DummyStrategy()


# ---------------------------------------------------------------------------
# GET /health
# ---------------------------------------------------------------------------
@api_router.get(
    "/health",
    response_model=HealthResponse,
    tags=["operations"],
    summary="Health check endpoint",
    description="Used by ALB health check. Returns engine status and version.",
)
async def health_check():
    settings = get_settings()
    strategy = _get_strategy()
    return HealthResponse(
        status="healthy",
        version=settings.app_version,
        environment=settings.environment,
        engine_mode=strategy.strategy_name,
        checks={
            "config_loaded": "ok",
            "detection_strategy": strategy.strategy_name,
            "dry_run_mode": "enabled" if settings.dry_run_mode else "disabled",
            "auto_containment": "enabled" if settings.enable_auto_containment else "disabled",
        },
    )


# ---------------------------------------------------------------------------
# POST /v1/finops/detect
# ---------------------------------------------------------------------------
@api_router.post(
    "/v1/finops/detect",
    response_model=DetectResponse,
    tags=["detection"],
    summary="Detect cost anomalies",
    description=(
        "Analyse a cost window against baseline and return anomaly detection result "
        "with alert routing, containment recommendation, and audit trail reference. "
        "Schema aligned with TF2 AI API Contract."
    ),
    responses={
        400: {"description": "Invalid request schema — do NOT retry"},
        429: {"description": "Rate limited — use exponential backoff"},
        503: {"description": "Engine unavailable — CDO must fallback to rule-based alert"},
    },
)
async def detect_anomaly(request: Request, body: DetectRequest):
    """
    Main detection endpoint. Flow:
    1. Extract tenant context from middleware
    2. Run detection strategy
    3. Determine alert routing
    4. Evaluate containment decision
    5. Write audit trail
    6. Return contract-compliant response
    """
    settings = get_settings()

    # --- 1. Tenant context ---
    tenant_id = getattr(request.state, "tenant_id", "unknown")
    correlation_id = getattr(request.state, "correlation_id", None)

    # --- 2. Detection ---
    strategy = _get_strategy()
    try:
        result = strategy.detect(
            cost_window=body.cost_window,
            baseline=body.baseline,
            tenant_id=tenant_id,
        )
    except Exception as exc:
        logger.error(
            "detection_failed | tenant=%s | strategy=%s | error=%s",
            tenant_id,
            strategy.strategy_name,
            str(exc),
        )
        raise HTTPException(status_code=503, detail="AI engine detection failed") from exc

    # --- 3. Alert routing ---
    alert_route = determine_alert_route(result)
    finance_summary = generate_finance_summary(result)
    engineering_summary = generate_engineering_summary(result)

    # --- 4. Containment evaluation ---
    # Use the first cost item's environment as representative
    resource_env = body.cost_window[0].environment if body.cost_window else "unknown"
    containment = evaluate_containment(
        result=result,
        resource_env=resource_env,
        policy=body.containment_policy,
        tenant_id=tenant_id,
    )

    # --- 5. Audit trail ---
    audit_entry = audit_logger.create_audit_entry(
        tenant_id=tenant_id,
        correlation_id=correlation_id,
        detection_result=result,
        containment_decision=containment,
    )

    # --- 6. Build response ---
    containment_detail = None
    if result.is_anomaly:
        containment_detail = ContainmentDetail(
            action=containment.action,
            target_resource=containment.target_resource,
            target_environment=containment.target_environment.value,
            dry_run_required=containment.dry_run_required,
            dry_run_passed=containment.dry_run_passed,
            rollback_path=containment.rollback_path,
        )

    return DetectResponse(
        anomaly=result.is_anomaly,
        anomaly_type=result.anomaly_type,
        severity=result.severity,
        confidence=result.confidence,
        reasoning=result.reasoning,
        finance_summary=finance_summary,
        engineering_summary=engineering_summary,
        alert_route=alert_route,
        suggested_action=containment.action,
        containment=containment_detail,
        dry_run_required=containment.dry_run_required,
        audit_id=audit_entry.audit_id,
        detected_at=datetime.now(timezone.utc),
        affected_resource_id=result.affected_resource_id,
    )
