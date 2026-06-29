"""Integration test: the sklearn ML overlay activates and /v1/detect still
returns a contract-valid response (CDO-callable end-to-end with metric AI).

The overlay is a SECONDARY signal (weight 0.30). This test proves wiring, not
detection quality — quality is measured by ai-engine/scripts/run_comparison.py.
"""
import os
from pathlib import Path

import pytest


OVERLAY = (
    Path(__file__).resolve().parents[3]
    / "AIO2" / "ai-engine" / "artifacts" / "overlay_model.joblib"
)


@pytest.mark.skipif(not OVERLAY.exists(), reason="overlay model not trained yet")
def test_sklearn_overlay_loads_and_scores():
    os.environ["AI_OVERLAY_MODEL"] = str(OVERLAY)

    from app.services.ml.statistical_detect_service import (
        _try_load_xgb_model,
        StatisticalDetectService,
    )

    overlay = _try_load_xgb_model()
    assert overlay is not None, "overlay should load from AI_OVERLAY_MODEL"

    svc = StatisticalDetectService()
    assert svc._xgb_available is True

    req_cur = {
        "line_item_usage_start_date": "2026-06-23T00:00:00Z",
        "line_item_usage_account_id": "200000000012",
        "line_item_product_code": "AmazonEC2",
        "line_item_usage_type": "BoxUsage:g4dn.xlarge",
        "line_item_resource_id": "i-0abcd1234efgh5678",
        "line_item_usage_amount": 24.0,
        "pricing_unit": "Hrs",
        "line_item_unblended_cost": 1500.0,
        "usage_density_24h": 1.0,
        "resource_tags_user_environment": "ml-research",
    }
    ce = {
        "date": "2026-06-23", "linked_account_id": "200000000012",
        "linked_account_name": "squad-ml-research", "service_code": "AmazonEC2",
        "service": "EC2", "region": "ap-southeast-1", "unblended_cost": 1500.0,
        "cost_ratio_to_7d_avg": 18.2, "day_of_week": 1,
        "is_weekend": False, "is_estimated": False,
    }
    util = {
        "resource_id": "i-0abcd1234efgh5678", "cpu_percent": 98.0,
        "memory_mib": 60000.0, "network_in_bytes": 5e8, "network_out_bytes": 5e8,
        "disk_io_ops": 100000.0, "gpu_utilization": 99.0,
        "hourly_cpu_percent": [98.0] * 24,
    }

    from app.schemas.detect import DetectRequest

    req = DetectRequest(
        data_source_type="RAW_JSON",
        business_context={
            "linked_account_id": "200000000012", "traffic_volume": 1000000,
            "traffic_source": "ALB", "campaign_flag": False,
            "load_test_flag": False, "migration_flag": False,
        },
        aws_cost_explorer_daily=[ce],
        aws_cur_line_items=[req_cur],
        resource_utilization_metrics=[util],
    )
    resp = svc.detect(req, correlation_id="test-corr-1")
    assert resp.success is True
    assert isinstance(resp.anomalies_list, list)
    for a in resp.anomalies_list:
        assert 0.0 <= a.confidence_score <= 1.0
        assert a.anomaly_id.startswith("ANM-")

    os.environ.pop("AI_OVERLAY_MODEL", None)
