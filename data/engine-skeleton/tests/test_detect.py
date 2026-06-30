"""Tests for POST /v1/detect."""

import re
import pytest
from fastapi.testclient import TestClient


ANM_PATTERN = re.compile(r"^ANM-\d{4}-\d{4}[A-Z]$")


class TestDetectSuccess:
    def test_returns_200(self, client, valid_headers, detect_payload):
        resp = client.post("/v1/detect", json=detect_payload, headers=valid_headers)
        assert resp.status_code == 200

    def test_response_has_required_fields(self, client, valid_headers, detect_payload):
        body = client.post("/v1/detect", json=detect_payload, headers=valid_headers).json()
        assert "success" in body
        assert "correlation_id" in body
        assert "anomalies_detected" in body
        assert "anomalies_list" in body

    def test_success_flag_is_true(self, client, valid_headers, detect_payload):
        body = client.post("/v1/detect", json=detect_payload, headers=valid_headers).json()
        assert body["success"] is True

    def test_anomaly_list_is_array(self, client, valid_headers, detect_payload):
        body = client.post("/v1/detect", json=detect_payload, headers=valid_headers).json()
        assert isinstance(body["anomalies_list"], list)

    def test_anomaly_id_format(self, client, valid_headers, detect_payload):
        """Run multiple times since mock is probabilistic."""
        for _ in range(10):
            body = client.post("/v1/detect", json=detect_payload, headers=valid_headers).json()
            for anomaly in body["anomalies_list"]:
                assert ANM_PATTERN.match(anomaly["anomaly_id"]), (
                    f"anomaly_id {anomaly['anomaly_id']} does not match ANM-YYYY-MMDD{{A-Z}}"
                )

    def test_anomaly_type_is_valid_enum(self, client, valid_headers, detect_payload):
        valid_types = {"runaway_usage", "idle_resource", "untagged_spend", "sudden_spike", "gradual_drift"}
        for _ in range(5):
            body = client.post("/v1/detect", json=detect_payload, headers=valid_headers).json()
            for anomaly in body["anomalies_list"]:
                assert anomaly["anomaly_type"] in valid_types

    def test_severity_is_valid_enum(self, client, valid_headers, detect_payload):
        for _ in range(5):
            body = client.post("/v1/detect", json=detect_payload, headers=valid_headers).json()
            for anomaly in body["anomalies_list"]:
                assert anomaly["severity"] in ("HIGH", "MEDIUM", "LOW")

    def test_confidence_score_in_range(self, client, valid_headers, detect_payload):
        for _ in range(5):
            body = client.post("/v1/detect", json=detect_payload, headers=valid_headers).json()
            for anomaly in body["anomalies_list"]:
                score = anomaly["confidence_score"]
                assert 0.0 <= score <= 1.0

    def test_alert_routing_has_both_flags(self, client, valid_headers, detect_payload):
        for _ in range(5):
            body = client.post("/v1/detect", json=detect_payload, headers=valid_headers).json()
            for anomaly in body["anomalies_list"]:
                routing = anomaly["alert_routing"]
                assert isinstance(routing["finance"], bool)
                assert isinstance(routing["engineering"], bool)

    def test_s3_pointer_mode(self, client, valid_headers, business_context):
        payload = {
            "data_source_type": "S3_POINTER",
            "business_context": business_context,
            "s3_bucket_uri": "s3://company-cdo-200000000012-telemetry/cur/cdo-02/2026-06-23.json.gz",
        }
        resp = client.post("/v1/detect", json=payload, headers=valid_headers)
        assert resp.status_code == 200

    def test_s3_pointer_key_alias(self, client, valid_headers, business_context):
        payload = {
            "data_source_type": "S3_POINTER",
            "business_context": business_context,
            "s3_pointer": "s3://company-cdo-200000000012-telemetry/cur/cdo-02/2026-06-23.json.gz",
        }
        resp = client.post("/v1/detect", json=payload, headers=valid_headers)
        assert resp.status_code == 200

    def test_dynamodb_feature_store_override(self, monkeypatch, client, valid_headers, detect_payload):
        mock_response = {
            "Responses": {
                "finops-feature-store-test": [
                    {
                        "resource_id": {"S": "i-0abcd1234efgh5678"},
                        "date": {"S": "2026-06-23"},
                        "rolling_avg": {"N": "10.0"},
                        "rolling_std": {"N": "1.0"},
                        "rolling_median": {"N": "10.0"},
                        "rolling_mad": {"N": "0.5"},
                        "slope_14d": {"N": "0.1"},
                        "cost_pct_change_28d": {"N": "0.05"},
                        "cpu_mean": {"N": "95.0"},
                        "usage_density_24h": {"N": "0.99"},
                        "peer_ratio": {"N": "1.0"},
                        "age_days": {"N": "15"},
                        "resource_tags_user_team": {"S": "overridden-team"},
                        "resource_tags_user_owner": {"S": "overridden-owner"},
                    }
                ]
            }
        }
        
        class MockDDB:
            def batch_get_item(self, **kwargs):
                return mock_response
                
        monkeypatch.setenv("DYNAMODB_FEATURE_STORE_TABLE", "finops-feature-store-test")
        monkeypatch.setattr("boto3.client", lambda service, region_name=None: MockDDB())
        
        # Set tags to None in payload to verify tag override when missing
        detect_payload["aws_cur_line_items"][0]["resource_tags_user_team"] = None
        detect_payload["aws_cur_line_items"][0]["resource_tags_user_owner"] = None

        resp = client.post("/v1/detect", json=detect_payload, headers=valid_headers)
        assert resp.status_code == 200
        body = resp.json()
        assert body["anomalies_detected"] is True
        assert body["anomalies_list"][0]["responsible_team"] == "overridden-team"


    def test_data_confidence_present(self, client, valid_headers, detect_payload):
        body = client.post("/v1/detect", json=detect_payload, headers=valid_headers).json()
        assert body["data_confidence"] in ("HIGH", "LOW")


class TestDetectValidation:
    def test_missing_required_header_returns_400(self, client, detect_payload):
        headers = {
            "Content-Type": "application/json",
            "X-Tenant-Id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",

        }
        resp = client.post("/v1/detect", json=detect_payload, headers=headers)
        assert resp.status_code == 400

    def test_missing_data_source_type_returns_400(self, client, valid_headers, ce_row, cur_row):
        payload = {
            "aws_cost_explorer_daily": [ce_row],
            "aws_cur_line_items": [cur_row],
        }
        resp = client.post("/v1/detect", json=payload, headers=valid_headers)
        assert resp.status_code == 400

    def test_missing_ce_data_returns_400(self, client, valid_headers, cur_row):
        payload = {
            "data_source_type": "RAW_JSON",
            "aws_cur_line_items": [cur_row],
        }
        resp = client.post("/v1/detect", json=payload, headers=valid_headers)
        assert resp.status_code == 400

    def test_raw_json_without_cur_returns_400(self, client, valid_headers, ce_row):
        payload = {
            "data_source_type": "RAW_JSON",
            "aws_cost_explorer_daily": [ce_row],
        }
        resp = client.post("/v1/detect", json=payload, headers=valid_headers)
        assert resp.status_code == 400

    def test_s3_pointer_without_uri_returns_400(self, client, valid_headers, ce_row):
        payload = {
            "data_source_type": "S3_POINTER",
            "aws_cost_explorer_daily": [ce_row],
        }
        resp = client.post("/v1/detect", json=payload, headers=valid_headers)
        assert resp.status_code == 400

    def test_stale_timestamp_returns_400(self, client, valid_headers, detect_payload):
        stale_headers = dict(valid_headers)
        stale_headers["X-Request-Timestamp"] = "2020-01-01T00:00:00Z"
        resp = client.post("/v1/detect", json=detect_payload, headers=stale_headers)
        assert resp.status_code == 400
        body = resp.json()
        assert body["error_code"] == "ERR_REPLAY_DETECTED"

    def test_invalid_dry_run_mode_returns_400(self, client, valid_headers, detect_payload):
        bad_headers = dict(valid_headers)
        bad_headers["X-Dry-Run-Mode"] = "yes"
        resp = client.post("/v1/detect", json=detect_payload, headers=bad_headers)
        assert resp.status_code == 400

    def test_invalid_account_id_pattern_returns_400(self, client, valid_headers, ce_row, cur_row):
        bad_row = dict(cur_row)
        bad_row["line_item_usage_account_id"] = "not-12-digits"
        payload = {
            "data_source_type": "RAW_JSON",
            "aws_cost_explorer_daily": [ce_row],
            "aws_cur_line_items": [bad_row],
        }
        resp = client.post("/v1/detect", json=payload, headers=valid_headers)
        assert resp.status_code == 400
