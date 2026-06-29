"""Shared pytest fixtures for the FinOps Watch AI Engine test suite."""

import os




os.environ.setdefault("RATE_LIMIT_PER_MIN", "0")

import datetime
import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture(scope="session")
def client() -> TestClient:

    with TestClient(app) as c:
        yield c




def _now_iso() -> str:
    return datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")


@pytest.fixture
def valid_headers() -> dict:
    return {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "X-Tenant-Id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
        "X-Idempotency-Key": "a1b2c3d4-e5f6-7890-abcd-ef1234567890:2026-06-26:daily-batch",
        "X-Payload-SHA256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
        "X-Request-Timestamp": _now_iso(),
        "X-Dry-Run-Mode": "true",
        "X-Correlation-Id": "9b1deb4d-3b7d-4bad-9bdd-2b0d7b3dcb6d",
    }




@pytest.fixture
def ce_row() -> dict:
    return {
        "date": "2026-06-23",
        "linked_account_id": "200000000012",
        "linked_account_name": "squad-ml-research",
        "service_code": "AmazonEC2",
        "service": "Amazon Elastic Compute Cloud - Compute",
        "region": "ap-southeast-1",
        "unblended_cost": 427.50,
        "cost_ratio_to_7d_avg": 18.2,
        "day_of_week": 1,
        "is_weekend": False,
        "is_estimated": False,
    }


@pytest.fixture
def cur_row() -> dict:
    return {
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
        "resource_tags_user_team": "squad-ml-core",
        "resource_tags_user_owner": "dev@company.com",
        "resource_tags_user_cost_center": "CC-9001",
    }


@pytest.fixture
def business_context() -> dict:
    return {
        "linked_account_id": "200000000012",
        "traffic_volume": 1250000,
        "traffic_source": "ALB",
        "campaign_flag": False,
        "load_test_flag": False,
        "migration_flag": False,
    }


@pytest.fixture
def detect_payload(ce_row, cur_row, business_context) -> dict:
    return {
        "data_source_type": "RAW_JSON",
        "is_ad_hoc": False,
        "telemetry_delay_event": False,
        "business_context": business_context,
        "aws_cost_explorer_daily": [ce_row],
        "aws_cur_line_items": [cur_row],
    }


@pytest.fixture
def decide_payload() -> dict:
    return {
        "correlation_id": "9b1deb4d-3b7d-4bad-9bdd-2b0d7b3dcb6d",
        "idempotency_key": "a1b2c3d4-e5f6-7890-abcd-ef1234567890:2026-06-26:daily-batch",
        "dry_run_mode": True,
        "anomaly_context": {
            "anomaly_id": "ANM-2026-0626A",
            "anomaly_type": "runaway_usage",
            "resource_id": "i-0abcd1234efgh5678",
            "environment": "ml-research",
            "unblended_cost_24h_usd": 427.50,
            "cost_ratio_to_7d_avg": 18.2,
            "responsible_team": "squad-ml-core",
            "cost_center_code": "CC-9001",
        },
    }


@pytest.fixture
def verify_payload(ce_row) -> dict:
    post_ce = dict(ce_row)
    post_ce["unblended_cost"] = 0.0
    post_ce["cost_ratio_to_7d_avg"] = 0.0
    return {
        "correlation_id": "9b1deb4d-3b7d-4bad-9bdd-2b0d7b3dcb6d",
        "idempotency_key": "b2c3d4e5-f6a7-8901-bcde-f12345678901:2026-06-26:daily-batch",
        "dry_run_mode": True,
        "action_executed": {
            "action": "tag-for-review",
            "target": "i-0abcd1234efgh5678",
            "status": "COMPLETED",
            "execution_time_seconds": 3,
        },
        "post_telemetry_window": {
            "data_source_type": "RAW_JSON",
            "aws_cost_explorer_daily": [post_ce],
            "aws_cur_line_items": [],
        },
    }
