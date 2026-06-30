"""
AWS Lambda entry point for the FinOps Watch AI Engine (container image).

Supports three invocation shapes so the CDO's `tf2-finops-*-ai-request` Lambda can
call it for both real-time HTTP and event-driven ingestion:

  1. HTTP event  (API Gateway / Lambda Function URL) → served by the full FastAPI
     app via Mangum (all /v1/* endpoints: detect, decide, verify, status, health).

  2. S3 event    (CUR/telemetry object lands in the save bucket) → INGEST that saved
     object, run anomaly detection + Bedrock-Nova LLM RCA, and (optionally) write the
     result back to S3.

  3. Direct invoke payload — e.g.
       {"s3_pointer": "s3://company-cdo-123-telemetry/cur/2026-06-30.json.gz"}
     or an inline detect body {"aws_cur_line_items": [...], ...}
     → same INGEST → detect → RCA pipeline.

Pipeline reused as-is (single source of truth): StatisticalDetectService.detect()
+ ProductionDecisionService.decide() (which calls app.services.ml.llm_rca → Bedrock
Nova Pro/Lite with the FinOps RCA system prompt).
"""
from __future__ import annotations

import json
import logging
import os
import uuid
from datetime import datetime, timezone

logger = logging.getLogger()
logger.setLevel(os.getenv("LOG_LEVEL", "INFO"))

_mangum = None  # lazy HTTP adapter


# --------------------------------------------------------------------------- #
# Event-type detection
# --------------------------------------------------------------------------- #

def _is_http_event(event: dict) -> bool:
    if not isinstance(event, dict):
        return False
    rc = event.get("requestContext")
    return bool(event.get("rawPath") or event.get("httpMethod")
                or (isinstance(rc, dict) and ("http" in rc or "httpMethod" in rc)))


def _is_s3_event(event: dict) -> bool:
    recs = event.get("Records") if isinstance(event, dict) else None
    return bool(isinstance(recs, list) and recs and isinstance(recs[0], dict) and "s3" in recs[0])


# --------------------------------------------------------------------------- #
# HTTP path (Mangum → FastAPI)
# --------------------------------------------------------------------------- #

def _http(event, context):
    global _mangum
    if _mangum is None:
        from mangum import Mangum
        from app.main import app
        _mangum = Mangum(app, lifespan="off")
    return _mangum(event, context)


# --------------------------------------------------------------------------- #
# Ingest helpers
# --------------------------------------------------------------------------- #

def _ingest_rows(s3_uri: str) -> list[dict]:
    """Read + decode CUR/telemetry rows from the saved S3 object (or S3_LOCAL_DIR)."""
    from app.services.ml.cur_source import load_cur_pointer
    rows = load_cur_pointer(s3_uri)
    logger.info("Ingested %d rows from %s", len(rows), s3_uri)
    return rows


def _default_business_context(cur_rows: list[dict]) -> dict:
    acct = next((r.get("line_item_usage_account_id") for r in cur_rows
                 if r.get("line_item_usage_account_id")), "000000000000")
    return {
        "linked_account_id": str(acct), "traffic_volume": 0.0, "traffic_source": "Mixed",
        "campaign_flag": False, "load_test_flag": False, "migration_flag": False,
        "scheduled_backup_flag": False, "batch_etl_flag": False,
    }


def _build_detect_request(payload: dict, cur_rows: list[dict] | None):
    from app.schemas.detect import DetectRequest
    body = {
        "data_source_type": "RAW_JSON",
        "business_context": payload.get("business_context") or _default_business_context(cur_rows or []),
        "aws_cur_line_items": cur_rows if cur_rows is not None else payload.get("aws_cur_line_items"),
        "aws_cost_explorer_daily": payload.get("aws_cost_explorer_daily") or [],
        "resource_utilization_metrics": payload.get("resource_utilization_metrics") or [],
        "is_ad_hoc": bool(payload.get("is_ad_hoc", True)),
    }
    return DetectRequest.model_validate(body)


# --------------------------------------------------------------------------- #
# Detect + LLM RCA pipeline
# --------------------------------------------------------------------------- #

def _run_pipeline(detect_request, run_rca: bool = True) -> dict:
    from app.services.ml.statistical_detect_service import StatisticalDetectService
    from app.services.ml.decision_service import ProductionDecisionService
    from app.services.ml.tenant_state import TenantStateService

    corr = str(uuid.uuid4())
    detect_svc = StatisticalDetectService()
    result = detect_svc.detect(detect_request, corr)

    out: dict = {
        "correlation_id": corr,
        "anomalies_detected": result.anomalies_detected,
        "data_confidence": getattr(result, "data_confidence", None),
        "anomalies": [a.model_dump(mode="json") for a in result.anomalies_list],
        "rca": [],
    }

    if run_rca and result.anomalies_list:
        decision = ProductionDecisionService(detect_svc, TenantStateService())
        from app.schemas.decide import DecideRequest, AnomalyContext
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        for a in result.anomalies_list[:int(os.getenv("RCA_MAX_ANOMALIES", "10"))]:
            try:
                ctx = AnomalyContext(
                    anomaly_id=a.anomaly_id, anomaly_type=a.anomaly_type, resource_id=a.resource_id,
                    environment=a.environment, unblended_cost_24h_usd=a.unblended_cost_24h_usd,
                    cost_ratio_to_7d_avg=a.cost_ratio_to_7d_avg, responsible_team=a.responsible_team,
                )
                dreq = DecideRequest(
                    correlation_id=corr,
                    idempotency_key=f"{uuid.uuid4()}:{today}:lambda-ingest",
                    dry_run_mode=True,
                    anomaly_context=ctx,
                )
                dec = decision.decide(dreq)
                out["rca"].append({
                    "anomaly_id": a.anomaly_id,
                    "matched_runbook": dec.matched_runbook,
                    "root_cause_analysis": dec.engineering_dashboard_data.root_cause_analysis.model_dump(mode="json"),
                    "executive_summary": dec.finance_dashboard_data.executive_summary,
                    "action_plan": [s.model_dump(mode="json") for s in dec.action_plan],
                    "applied_payload": dec.applied_payload.model_dump(mode="json"),
                })
            except Exception as exc:  # noqa: BLE001 — one bad anomaly must not fail the batch
                logger.warning("RCA failed for %s: %s", a.anomaly_id, exc)
    return out


def _maybe_save(result: dict, payload: dict) -> str | None:
    """Write results back to S3 if output_s3_uri or OUTPUT_S3_BUCKET is configured."""
    uri = payload.get("output_s3_uri")
    if not uri:
        bucket = os.getenv("OUTPUT_S3_BUCKET")
        if bucket:
            uri = f"s3://{bucket}/finops-results/{result['correlation_id']}.json"
    if not uri:
        return None
    try:
        import boto3
        from app.services.ml.cur_source import _parse_s3_uri  # type: ignore
        bucket, key = _parse_s3_uri(uri)
        boto3.client("s3", region_name=os.getenv("AWS_DEFAULT_REGION", "ap-southeast-1")).put_object(
            Bucket=bucket, Key=key, Body=json.dumps(result).encode(), ContentType="application/json")
        logger.info("Saved results to %s", uri)
        return uri
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not save results to %s: %s", uri, exc)
        return None


# --------------------------------------------------------------------------- #
# Lambda entry point
# --------------------------------------------------------------------------- #

def handler(event, context):
    # 1. HTTP (API Gateway / Function URL) → full FastAPI app
    if _is_http_event(event):
        return _http(event, context)

    # 2. S3 trigger → ingest the saved object
    if _is_s3_event(event):
        rec = event["Records"][0]["s3"]
        bucket = rec["bucket"]["name"]
        key = rec["object"]["key"]
        s3_uri = f"s3://{bucket}/{key}"
        rows = _ingest_rows(s3_uri)
        result = _run_pipeline(_build_detect_request(event, rows))
        result["ingested_from"] = s3_uri
        result["saved_to"] = _maybe_save(result, event)
        return result

    # 3. Direct invoke — s3_pointer / s3_bucket_uri OR inline detect body
    payload = event if isinstance(event, dict) else {}
    pointer = payload.get("s3_pointer") or payload.get("s3_bucket_uri")
    rows = _ingest_rows(pointer) if pointer else None
    if rows is None and not payload.get("aws_cur_line_items"):
        return {"statusCode": 400, "error": "No data: provide an HTTP request, S3 event, "
                "'s3_pointer', or 'aws_cur_line_items'."}
    result = _run_pipeline(_build_detect_request(payload, rows))
    if pointer:
        result["ingested_from"] = pointer
    result["saved_to"] = _maybe_save(result, payload)
    return result
