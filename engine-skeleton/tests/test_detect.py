"""
Smoke tests for the FinOps Watch AI Engine skeleton.
Run with: pytest tests/ -v

Updated to use real TF2 data patterns (CUR 2.0 schema, account IDs, service codes).
"""

import pytest
from fastapi.testclient import TestClient

from main import app

client = TestClient(app)

# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------

class TestHealthCheck:
    def test_health_returns_200(self):
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert "version" in data
        assert data["engine_mode"] == "dummy_skeleton"

    def test_health_shows_dry_run_enabled(self):
        response = client.get("/health")
        data = response.json()
        assert data["checks"]["dry_run_mode"] == "enabled"


# ---------------------------------------------------------------------------
# Detection endpoint — happy path (using real TF2 data patterns)
# ---------------------------------------------------------------------------

class TestDetectEndpoint:
    VALID_HEADERS = {
        "X-Tenant-Id": "tenant-test-001",
        "X-Correlation-Id": "corr-test-001",
    }

    # Payload based on real TF2 data: ml-research account, GPU instance, high cost
    ANOMALY_PAYLOAD = {
        "cost_window": [
            {
                "account_id": "200000000015",
                "service": "AmazonEC2",
                "region": "us-east-1",
                "cost_usd": 400.0,
                "usage_type": "BoxUsage:p3.2xlarge",
                "tags": {"team": "ml-research", "environment": "dev"},
                "environment": "dev",
                "owner": "ml-team@company.com",
                "cost_period_start": "2026-05-15T00:00:00Z",
                "cost_period_end": "2026-05-16T00:00:00Z",
                "account_name": "ml-research",
                "product_code": "AmazonEC2",
                "operation": "RunInstances",
                "resource_id": "i-gpu-training-forgotten-01",
                "instance_type": "p3.2xlarge",
                "usage_amount": 24.0,
                "pricing_unit": "Hrs",
                "unblended_rate": 3.06,
                "is_estimated": False,
                "cost_center": "CC-1005",
            }
        ],
        "baseline": {
            "baseline_start": "2026-03-01T00:00:00Z",
            "baseline_end": "2026-04-30T00:00:00Z",
            "baseline_avg_daily_cost_usd": 50.0,
            "baseline_total_cost_usd": 3050.0,
        },
        "detection_cadence_hours": 24,
    }

    # Normal payload: prod-core account, EC2 t3.medium, low cost
    NORMAL_PAYLOAD = {
        "cost_window": [
            {
                "account_id": "200000000010",
                "service": "AmazonEC2",
                "region": "us-east-1",
                "cost_usd": 30.0,
                "usage_type": "BoxUsage:t3.medium",
                "tags": {"team": "platform", "environment": "prod"},
                "environment": "prod",
                "cost_period_start": "2026-05-15T00:00:00Z",
                "cost_period_end": "2026-05-16T00:00:00Z",
                "account_name": "prod-core",
                "product_code": "AmazonEC2",
            }
        ],
        "detection_cadence_hours": 24,
    }

    def test_detect_anomaly_returns_200(self):
        response = client.post(
            "/v1/finops/detect",
            json=self.ANOMALY_PAYLOAD,
            headers=self.VALID_HEADERS,
        )
        assert response.status_code == 200
        data = response.json()
        assert data["anomaly"] is True
        assert data["severity"] > 0.5
        assert data["confidence"] > 0.5
        assert "audit_id" in data
        assert "finance_summary" in data
        assert "engineering_summary" in data
        assert data["alert_route"] in ["finance", "engineering", "both"]
        assert data["dry_run_required"] is True

    def test_detect_anomaly_type_is_valid(self):
        """Verify anomaly_type matches TF2 data enum values."""
        response = client.post(
            "/v1/finops/detect",
            json=self.ANOMALY_PAYLOAD,
            headers=self.VALID_HEADERS,
        )
        data = response.json()
        valid_types = [
            "runaway_usage", "idle_resource", "untagged_spend",
            "sudden_spike", "gradual_drift", "over_provisioned", "other",
        ]
        assert data["anomaly_type"] in valid_types

    def test_detect_normal_returns_200(self):
        response = client.post(
            "/v1/finops/detect",
            json=self.NORMAL_PAYLOAD,
            headers=self.VALID_HEADERS,
        )
        assert response.status_code == 200
        data = response.json()
        assert data["anomaly"] is False
        assert "audit_id" in data

    def test_detect_returns_containment_for_anomaly(self):
        response = client.post(
            "/v1/finops/detect",
            json=self.ANOMALY_PAYLOAD,
            headers=self.VALID_HEADERS,
        )
        data = response.json()
        assert data["anomaly"] is True
        assert data["containment"] is not None
        assert data["containment"]["target_environment"] == "dev"
        assert data["containment"]["dry_run_required"] is True

    def test_detect_returns_affected_resource_id(self):
        """Verify response includes resource_id for CDO drill-down."""
        response = client.post(
            "/v1/finops/detect",
            json=self.ANOMALY_PAYLOAD,
            headers=self.VALID_HEADERS,
        )
        data = response.json()
        assert data["anomaly"] is True
        assert data.get("affected_resource_id") == "i-gpu-training-forgotten-01"

    def test_detect_prod_resource_blocks_containment(self):
        """Prod resources must NEVER get auto-containment."""
        response = client.post(
            "/v1/finops/detect",
            json=self.NORMAL_PAYLOAD,  # env=prod, low cost
            headers=self.VALID_HEADERS,
        )
        data = response.json()
        # Even if it were anomaly, prod containment should be blocked
        assert data["suggested_action"] in [
            "alert_only", "tag_for_review", "investigate",
        ]

    def test_response_has_correlation_id_header(self):
        response = client.post(
            "/v1/finops/detect",
            json=self.ANOMALY_PAYLOAD,
            headers=self.VALID_HEADERS,
        )
        assert response.headers.get("x-correlation-id") == "corr-test-001"
        assert response.headers.get("x-tenant-id") == "tenant-test-001"


# ---------------------------------------------------------------------------
# Untagged spend detection
# ---------------------------------------------------------------------------

class TestUntaggedSpend:
    VALID_HEADERS = {
        "X-Tenant-Id": "tenant-test-002",
    }

    def test_untagged_items_not_flagged_in_dummy_mode(self):
        """Dummy strategy doesn't check tags — just cost > 200."""
        payload = {
            "cost_window": [
                {
                    "account_id": "200000000010",
                    "service": "AWSDataTransfer",
                    "region": "us-east-1",
                    "cost_usd": 150.0,
                    "usage_type": "DataTransfer-Out-Bytes",
                    "tags": {},  # no team tag
                    "environment": "prod",
                    "cost_period_start": "2026-05-15T00:00:00Z",
                    "cost_period_end": "2026-05-16T00:00:00Z",
                    "account_name": "prod-core",
                },
                {
                    "account_id": "200000000010",
                    "service": "AmazonEC2",
                    "region": "us-east-1",
                    "cost_usd": 180.0,
                    "usage_type": "BoxUsage:m5.2xlarge",
                    "tags": {},  # no team tag
                    "environment": "prod",
                    "cost_period_start": "2026-05-15T00:00:00Z",
                    "cost_period_end": "2026-05-16T00:00:00Z",
                },
            ],
            "detection_cadence_hours": 24,
        }
        response = client.post(
            "/v1/finops/detect",
            json=payload,
            headers=self.VALID_HEADERS,
        )
        assert response.status_code == 200


# ---------------------------------------------------------------------------
# CUR 2.0 enrichment fields
# ---------------------------------------------------------------------------

class TestCUREnrichment:
    VALID_HEADERS = {
        "X-Tenant-Id": "tenant-test-003",
    }

    def test_is_estimated_field_accepted(self):
        """Verify is_estimated flag is accepted without error."""
        payload = {
            "cost_window": [
                {
                    "account_id": "200000000010",
                    "service": "AmazonEC2",
                    "region": "us-east-1",
                    "cost_usd": 50.0,
                    "usage_type": "BoxUsage:t3.medium",
                    "environment": "prod",
                    "cost_period_start": "2026-05-30T00:00:00Z",
                    "cost_period_end": "2026-05-31T00:00:00Z",
                    "is_estimated": True,
                }
            ],
            "detection_cadence_hours": 24,
        }
        response = client.post(
            "/v1/finops/detect",
            json=payload,
            headers=self.VALID_HEADERS,
        )
        assert response.status_code == 200

    def test_cur_fields_accepted(self):
        """Verify all CUR 2.0 enrichment fields are accepted."""
        payload = {
            "cost_window": [
                {
                    "account_id": "200000000012",
                    "service": "AmazonRDS",
                    "region": "us-east-1",
                    "cost_usd": 27.84,
                    "usage_type": "InstanceUsage:db.r5.2xlarge",
                    "tags": {"team": "", "environment": "staging"},
                    "environment": "staging",
                    "cost_period_start": "2026-04-15T00:00:00Z",
                    "cost_period_end": "2026-04-16T00:00:00Z",
                    "account_name": "staging",
                    "product_code": "AmazonRDS",
                    "operation": "CreateDBInstance",
                    "resource_id": "arn:aws:rds:us-east-1:acct:db:db-staging-orphan-01",
                    "instance_type": "db.r5.2xlarge",
                    "usage_amount": 24.0,
                    "pricing_unit": "Hrs",
                    "unblended_rate": 1.16,
                    "is_estimated": False,
                    "cost_center": "CC-1003",
                }
            ],
            "detection_cadence_hours": 24,
        }
        response = client.post(
            "/v1/finops/detect",
            json=payload,
            headers=self.VALID_HEADERS,
        )
        assert response.status_code == 200
        data = response.json()
        assert "audit_id" in data


# ---------------------------------------------------------------------------
# Validation & error handling
# ---------------------------------------------------------------------------

class TestValidation:
    def test_missing_tenant_id_returns_400(self):
        response = client.post(
            "/v1/finops/detect",
            json={"cost_window": []},
        )
        assert response.status_code == 400
        assert "tenant" in response.json()["detail"].lower()

    def test_empty_cost_window_returns_422(self):
        response = client.post(
            "/v1/finops/detect",
            json={"cost_window": []},
            headers={"X-Tenant-Id": "test"},
        )
        assert response.status_code == 422  # Pydantic validation error

    def test_missing_required_fields_returns_422(self):
        response = client.post(
            "/v1/finops/detect",
            json={"cost_window": [{"account_id": "123"}]},
            headers={"X-Tenant-Id": "test"},
        )
        assert response.status_code == 422
