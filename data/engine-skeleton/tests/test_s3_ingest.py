"""S3_POINTER ingestion: the engine fetches + parses an Athena CUR export and
actually detects on it (offline via S3_LOCAL_DIR fallback).

Covers Kiet's converged path: CDO Athena query → JSON.gz → S3_POINTER.
Also checks JSON-lines and .csv.gz parsing in the loader.
"""
import csv
import gzip
import io
import json
import os
from pathlib import Path

import pytest

BUCKET = "company-cdo-200000000012-telemetry"
KEY = "cur/cdo-02/2026-06-23.json.gz"
S3_URI = f"s3://{BUCKET}/{KEY}"

CUR_ROWS = [
    {
        "line_item_usage_start_date": "2026-06-23T00:00:00Z",
        "line_item_usage_account_id": "200000000012",
        "line_item_product_code": "AmazonEC2",
        "line_item_usage_type": "BoxUsage:p3.2xlarge",
        "line_item_resource_id": "i-0fbgpu00000004",
        "line_item_usage_amount": 24.0,
        "pricing_unit": "Hrs",
        "line_item_unblended_cost": 1468.8,
        "usage_density_24h": 1.0,
        "resource_tags_user_environment": "ml-research",

    }
]


def _write_gz(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(gzip.compress(data))


def test_loader_json_array(tmp_path, monkeypatch):
    from app.services.ml.cur_source import load_cur_pointer

    _write_gz(tmp_path / KEY, json.dumps(CUR_ROWS).encode())
    monkeypatch.setenv("S3_LOCAL_DIR", str(tmp_path))
    rows = load_cur_pointer(S3_URI)
    assert len(rows) == 1
    assert rows[0]["line_item_resource_id"] == "i-0fbgpu00000004"


def test_loader_json_lines(tmp_path, monkeypatch):
    """Athena UNLOAD format=JSON produces one object per line."""
    from app.services.ml.cur_source import load_cur_pointer

    lines = "\n".join(json.dumps(r) for r in CUR_ROWS)
    _write_gz(tmp_path / KEY, lines.encode())
    monkeypatch.setenv("S3_LOCAL_DIR", str(tmp_path))
    assert len(load_cur_pointer(S3_URI)) == 1


def test_loader_csv_gz(tmp_path, monkeypatch):
    from app.services.ml.cur_source import load_cur_pointer

    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=list(CUR_ROWS[0].keys()))
    w.writeheader()
    w.writerows(CUR_ROWS)
    csv_key = KEY.replace(".json.gz", ".csv.gz")
    _write_gz(tmp_path / csv_key, buf.getvalue().encode())
    monkeypatch.setenv("S3_LOCAL_DIR", str(tmp_path))
    rows = load_cur_pointer(f"s3://{BUCKET}/{csv_key}")
    assert len(rows) == 1


def test_loader_missing_object_returns_empty(tmp_path, monkeypatch):
    from app.services.ml.cur_source import load_cur_pointer

    monkeypatch.setenv("S3_LOCAL_DIR", str(tmp_path))
    assert load_cur_pointer(S3_URI) == []


def test_detect_via_s3_pointer(tmp_path, monkeypatch):
    """End-to-end: S3_POINTER → fetch → parse → detect."""
    from app.services.ml.statistical_detect_service import StatisticalDetectService
    from app.schemas.detect import DetectRequest

    _write_gz(tmp_path / KEY, json.dumps(CUR_ROWS).encode())
    monkeypatch.setenv("S3_LOCAL_DIR", str(tmp_path))

    req = DetectRequest(
        data_source_type="S3_POINTER",
        s3_bucket_uri=S3_URI,
        business_context={
            "linked_account_id": "200000000012", "traffic_volume": 1000000,
            "traffic_source": "ALB", "campaign_flag": False,
            "load_test_flag": False, "migration_flag": False,
        },
    )
    resp = StatisticalDetectService().detect(req, correlation_id="s3-corr-1")
    assert resp.success is True

    assert resp.anomalies_detected is True
    assert any(a.anomaly_type.value == "untagged_spend" for a in resp.anomalies_list)


def test_detect_via_csv_gz_pointer_no_conversion(tmp_path, monkeypatch):
    """Option B: native AWS CUR .csv.gz pointer — CDO uploads, no conversion.

    Proves the schema pattern now ACCEPTS .csv.gz (not just the loader) and the
    engine detects on it end-to-end.
    """
    from app.services.ml.statistical_detect_service import StatisticalDetectService
    from app.schemas.detect import DetectRequest

    csv_key = KEY.replace(".json.gz", ".csv.gz")
    csv_uri = f"s3://{BUCKET}/{csv_key}"
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=list(CUR_ROWS[0].keys()))
    w.writeheader()
    w.writerows(CUR_ROWS)
    _write_gz(tmp_path / csv_key, buf.getvalue().encode())
    monkeypatch.setenv("S3_LOCAL_DIR", str(tmp_path))


    req = DetectRequest(
        data_source_type="S3_POINTER",
        s3_bucket_uri=csv_uri,
        business_context={
            "linked_account_id": "200000000012", "traffic_volume": 1000000,
            "traffic_source": "ALB", "campaign_flag": False,
            "load_test_flag": False, "migration_flag": False,
        },
    )
    resp = StatisticalDetectService().detect(req, correlation_id="s3-csv-1")
    assert resp.success is True
    assert resp.anomalies_detected is True
