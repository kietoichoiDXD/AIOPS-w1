# FinOps Watch — AI Engine (Mock)

**Contract:** `contracts/ai-api-contract.md` v1.1.0  
**Stack:** Python 3.12 · FastAPI · Pydantic v2 · Uvicorn  
**Status:** Mock implementation — production ML models not yet integrated

---

## Overview

This is the **mock AI Engine** for TF2 FinOps Watch.  
It implements all 6 API endpoints defined in the signed AI API Contract so that the CDO team can begin integration immediately, without waiting for Isolation Forest or Amazon Nova to be ready.

The mock layer is fully isolated. When ML models are ready, swap `MockDetectService` → `IsolationForestDetectService` and `MockDecisionService` → `ProductionDecisionService` without touching any router, schema, or test code.

---

## Endpoints

| Method | Path | Description |
|---|---|---|
| `GET` | `/health` | ALB / ECS health check (no auth) |
| `POST` | `/v1/detect` | Detect cost anomalies from CUR + CE telemetry |
| `POST` | `/v1/decide` | Plan containment action for a detected anomaly |
| `POST` | `/v1/verify` | Evaluate post-action telemetry → DONE/RETRY/ROLLBACK/ESCALATE |
| `GET` | `/v1/status/{anomaly_id}` | Poll remediation status |
| `POST` | `/v1/audit/{audit_id}/rollback` | Record manual rollback (false-positive feedback) |

Swagger UI: `http://localhost:8080/docs`  
ReDoc: `http://localhost:8080/redoc`

---

## Anomaly Types

| Type | Severity | Primary Signal |
|---|---|---|
| `runaway_usage` | HIGH | `usage_density_24h ≥ 0.95` for >24h |
| `idle_resource` | MEDIUM | `usage_density_24h ≤ 0.05` for >3 days |
| `untagged_spend` | MEDIUM | `resource_tags_user_team = null` + cost > threshold |
| `sudden_spike` | HIGH | `cost_ratio_to_7d_avg > 3.0` in 1 day |
| `gradual_drift` | LOW | Trend slope > 5%/week for 4 weeks |

---

## Decision Rules (from contract §7)

| Environment | Containment Action |
|---|---|
| `prod`, `prod-core`, `prod-payments` | `tag-for-review` only (hard boundary) |
| `staging` | `time-gated-countdown` (4h countdown → auto-shutdown) |
| `dev`, `sandbox` | `auto-shutdown` |
| `ml-research` | `auto-shutdown` |
| `data-analytics` | `quota-cap` |

---

## Quick Start

### Local (no Docker)

```bash
cd engine-skeleton
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8080
```

### Docker

```bash
cd engine-skeleton
docker compose up --build
```

Open `http://localhost:8080/docs` for interactive Swagger UI.

---

## Running Tests

```bash
cd engine-skeleton
pytest tests/ -v --cov=app --cov-report=term-missing
```

Expected coverage: **≥ 80%**

---

## Required Headers (all v1 endpoints)

| Header | Format | Notes |
|---|---|---|
| `X-Tenant-Id` | UUID v4 | Tenant isolation |
| `X-Idempotency-Key` | `{uuid}:{date}:{batch-type}` | Anti-duplicate processing |
| `X-Payload-SHA256` | SHA256 hex string | Body integrity check |
| `X-Request-Timestamp` | RFC3339 UTC | Reject if skew > 300s |
| `X-Dry-Run-Mode` | `"true"` or `"false"` | Must match body intent |
| `X-Correlation-Id` | UUID v4 | Optional; auto-generated if absent |

---

## Example curl Commands

### Health Check

```bash
curl -s http://localhost:8080/health | python -m json.tool
```

### Detect

```bash
NOW=$(date -u +"%Y-%m-%dT%H:%M:%SZ")

curl -s -X POST http://localhost:8080/v1/detect \
  -H "Content-Type: application/json" \
  -H "X-Tenant-Id: a1b2c3d4-e5f6-7890-abcd-ef1234567890" \
  -H "X-Idempotency-Key: a1b2c3d4-e5f6-7890-abcd-ef1234567890:2026-06-26:daily-batch" \
  -H "X-Payload-SHA256: e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855" \
  -H "X-Request-Timestamp: $NOW" \
  -H "X-Dry-Run-Mode: true" \
  -H "X-Correlation-Id: 9b1deb4d-3b7d-4bad-9bdd-2b0d7b3dcb6d" \
  -d '{
    "data_source_type": "RAW_JSON",
    "aws_cost_explorer_daily": [{
      "date": "2026-06-23",
      "linked_account_id": "200000000012",
      "linked_account_name": "squad-ml-research",
      "service_code": "AmazonEC2",
      "service": "Amazon Elastic Compute Cloud - Compute",
      "region": "ap-southeast-1",
      "unblended_cost": 427.50,
      "cost_ratio_to_7d_avg": 18.2,
      "day_of_week": 1,
      "is_weekend": false,
      "is_estimated": false
    }],
    "aws_cur_line_items": [{
      "line_item_usage_start_date": "2026-06-23T00:00:00Z",
      "line_item_usage_account_id": "200000000012",
      "line_item_product_code": "AmazonEC2",
      "line_item_usage_type": "BoxUsage:g4dn.xlarge",
      "line_item_resource_id": "i-0abcd1234efgh5678",
      "line_item_usage_amount": 24.0,
      "pricing_unit": "Hrs",
      "line_item_unblended_cost": 427.50,
      "usage_density_24h": 1.0,
      "resource_tags_user_environment": "ml-research",
      "resource_tags_user_team": "squad-ml-core"
    }]
  }' | python -m json.tool
```

### Decide

```bash
NOW=$(date -u +"%Y-%m-%dT%H:%M:%SZ")

curl -s -X POST http://localhost:8080/v1/decide \
  -H "Content-Type: application/json" \
  -H "X-Tenant-Id: a1b2c3d4-e5f6-7890-abcd-ef1234567890" \
  -H "X-Idempotency-Key: a1b2c3d4-e5f6-7890-abcd-ef1234567890:2026-06-26:daily-batch" \
  -H "X-Payload-SHA256: e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855" \
  -H "X-Request-Timestamp: $NOW" \
  -H "X-Dry-Run-Mode: true" \
  -H "X-Correlation-Id: 9b1deb4d-3b7d-4bad-9bdd-2b0d7b3dcb6d" \
  -d '{
    "correlation_id": "9b1deb4d-3b7d-4bad-9bdd-2b0d7b3dcb6d",
    "idempotency_key": "a1b2c3d4-e5f6-7890-abcd-ef1234567890:2026-06-26:daily-batch",
    "dry_run_mode": true,
    "anomaly_context": {
      "anomaly_id": "ANM-2026-0626A",
      "anomaly_type": "runaway_usage",
      "resource_id": "i-0abcd1234efgh5678",
      "environment": "ml-research",
      "unblended_cost_24h_usd": 427.50,
      "cost_ratio_to_7d_avg": 18.2,
      "responsible_team": "squad-ml-core",
      "cost_center_code": "CC-9001"
    }
  }' | python -m json.tool
```

### Verify

```bash
NOW=$(date -u +"%Y-%m-%dT%H:%M:%SZ")

curl -s -X POST http://localhost:8080/v1/verify \
  -H "Content-Type: application/json" \
  -H "X-Tenant-Id: a1b2c3d4-e5f6-7890-abcd-ef1234567890" \
  -H "X-Idempotency-Key: b2c3d4e5-f6a7-8901-bcde-f12345678901:2026-06-26:daily-batch" \
  -H "X-Payload-SHA256: e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855" \
  -H "X-Request-Timestamp: $NOW" \
  -H "X-Dry-Run-Mode: true" \
  -H "X-Correlation-Id: 9b1deb4d-3b7d-4bad-9bdd-2b0d7b3dcb6d" \
  -d '{
    "correlation_id": "9b1deb4d-3b7d-4bad-9bdd-2b0d7b3dcb6d",
    "idempotency_key": "b2c3d4e5-f6a7-8901-bcde-f12345678901:2026-06-26:daily-batch",
    "dry_run_mode": true,
    "action_executed": {
      "action": "tag-for-review",
      "target": "i-0abcd1234efgh5678",
      "status": "COMPLETED",
      "execution_time_seconds": 3
    },
    "post_telemetry_window": {
      "data_source_type": "RAW_JSON",
      "aws_cost_explorer_daily": [{
        "date": "2026-06-24",
        "linked_account_id": "200000000012",
        "linked_account_name": "squad-ml-research",
        "service_code": "AmazonEC2",
        "service": "Amazon Elastic Compute Cloud",
        "region": "ap-southeast-1",
        "unblended_cost": 0.0,
        "cost_ratio_to_7d_avg": 0.0,
        "day_of_week": 2,
        "is_weekend": false,
        "is_estimated": false
      }],
      "aws_cur_line_items": []
    }
  }' | python -m json.tool
```

### Status Poll

```bash
curl -s http://localhost:8080/v1/status/ANM-2026-0626A \
  -H "X-Tenant-Id: a1b2c3d4-e5f6-7890-abcd-ef1234567890" | python -m json.tool
```

### Manual Rollback

```bash
curl -s -X POST http://localhost:8080/v1/audit/ANM-2026-0626A/rollback \
  -H "Content-Type: application/json" \
  -H "X-Tenant-Id: a1b2c3d4-e5f6-7890-abcd-ef1234567890" \
  -d '{
    "reason": "False positive — instance is used for approved experiment",
    "rolled_back_by": "engineer@company.com"
  }' | python -m json.tool
```

---

## Project Structure

```
engine-skeleton/
├── app/
│   ├── main.py                        # FastAPI app, lifespan, exception handlers
│   ├── config/
│   │   └── settings.py                # Pydantic Settings (env-var driven)
│   ├── models/
│   │   └── enums.py                   # All contract enums
│   ├── schemas/
│   │   ├── common.py                  # ErrorResponse
│   │   ├── detect.py                  # DetectRequest + DetectResponse
│   │   ├── decide.py                  # DecideRequest + DecideResponse
│   │   ├── verify.py                  # VerifyRequest + VerifyResponse
│   │   ├── health.py                  # HealthResponse
│   │   └── status.py                  # RemediationStatusResponse + RollbackRequest/Response
│   ├── services/
│   │   ├── base.py                    # Abstract DetectService + DecisionService
│   │   ├── mock_detect_service.py     # Mock Isolation Forest
│   │   └── mock_decision_service.py   # Mock runbook + verify + rollback
│   └── routers/
│       ├── health.py                  # GET /health
│       ├── detect.py                  # POST /v1/detect
│       ├── decide.py                  # POST /v1/decide
│       ├── verify.py                  # POST /v1/verify
│       └── status.py                  # GET /v1/status/{id} + POST /v1/audit/{id}/rollback
├── tests/
│   ├── conftest.py                    # Fixtures: client, headers, payloads
│   ├── test_health.py
│   ├── test_detect.py
│   ├── test_decide.py
│   └── test_verify.py
├── requirements.txt
├── Dockerfile
├── docker-compose.yml
├── .env.example
└── README.md
```

---

## Replacing Mock with Production Services

1. Create `app/services/production_detect_service.py` implementing `DetectService`
2. Create `app/services/production_decision_service.py` implementing `DecisionService`
3. In `app/main.py` lifespan, swap `MockDetectService()` → `ProductionDetectService()`
4. No router, schema, or test changes required

Production implementations will use:
- **Isolation Forest** (primary anomaly detection) — scikit-learn or SageMaker endpoint
- **Random Cut Forest** (benchmark) — Amazon SageMaker RCF
- **Amazon Nova** (explanation generation) — Amazon Bedrock
- **DynamoDB** (state store) — replaces in-memory `_status_store`
- **SQS** (alert routing) — replaces direct response construction

---

*Contract: `contracts/ai-api-contract.md` v1.1.0 — frozen, signed 2026-06-25*
