"""Tests for POST /v1/verify and GET /v1/status/{anomaly_id}."""

import pytest
from fastapi.testclient import TestClient


class TestVerifySuccess:
    def test_returns_200(self, client, valid_headers, verify_payload):
        resp = client.post("/v1/verify", json=verify_payload, headers=valid_headers)
        assert resp.status_code == 200

    def test_response_has_required_fields(self, client, valid_headers, verify_payload):
        body = client.post("/v1/verify", json=verify_payload, headers=valid_headers).json()
        assert "success" in body
        assert "regression_detected" in body
        assert "next_action" in body

    def test_next_action_is_valid_enum(self, client, valid_headers, verify_payload):
        valid_actions = {"DONE", "RETRY", "ROLLBACK", "ESCALATE"}
        for _ in range(10):
            body = client.post("/v1/verify", json=verify_payload, headers=valid_headers).json()
            assert body["next_action"] in valid_actions

    def test_failed_action_triggers_rollback(self, client, valid_headers, verify_payload):
        payload = dict(verify_payload)
        payload["action_executed"] = dict(verify_payload["action_executed"])
        payload["action_executed"]["status"] = "FAILED"
        body = client.post("/v1/verify", json=payload, headers=valid_headers).json()
        assert body["next_action"] == "ROLLBACK"
        assert body["success"] is False

    def test_escalate_includes_bundle(self, client, valid_headers, verify_payload):
        """
        We can't guarantee ESCALATE in a single call since it's probabilistic (1%),
        so we test the schema structure when escalation_bundle is present.
        """
        for _ in range(50):
            body = client.post("/v1/verify", json=verify_payload, headers=valid_headers).json()
            if body["next_action"] == "ESCALATE":
                bundle = body.get("escalation_bundle")
                assert bundle is not None
                assert "reason" in bundle
                return

        pytest.skip("ESCALATE not triggered in 50 attempts (expected with 1% probability)")


class TestVerifyValidation:
    def test_missing_headers_returns_400(self, client, verify_payload):
        resp = client.post("/v1/verify", json=verify_payload, headers={"Content-Type": "application/json"})
        assert resp.status_code == 400

    def test_missing_correlation_id_returns_400(self, client, valid_headers, verify_payload):
        payload = dict(verify_payload)
        del payload["correlation_id"]
        resp = client.post("/v1/verify", json=payload, headers=valid_headers)
        assert resp.status_code == 400

    def test_invalid_action_status_enum_returns_400(self, client, valid_headers, verify_payload):
        payload = dict(verify_payload)
        payload["action_executed"] = dict(verify_payload["action_executed"])
        payload["action_executed"]["status"] = "UNKNOWN"
        resp = client.post("/v1/verify", json=payload, headers=valid_headers)
        assert resp.status_code == 400

    def test_empty_post_telemetry_returns_400(self, client, valid_headers, verify_payload):
        payload = dict(verify_payload)
        del payload["post_telemetry_window"]
        resp = client.post("/v1/verify", json=payload, headers=valid_headers)
        assert resp.status_code == 400


class TestStatus:
    def test_status_not_found_returns_404(self, client):
        resp = client.get("/v1/status/ANM-2026-0101Z", headers={"X-Tenant-Id": "test-tenant"})
        assert resp.status_code == 404
        body = resp.json()
        assert body["error_code"] == "ERR_ANOMALY_NOT_FOUND"

    def test_invalid_anomaly_id_format_returns_400(self, client):
        resp = client.get("/v1/status/INVALID-ID", headers={"X-Tenant-Id": "test-tenant"})
        assert resp.status_code == 400

    def test_status_found_after_detect(self, client, valid_headers, detect_payload):
        """Detect creates a status record; it should be retrievable by the owning tenant."""
        owner_tenant = valid_headers["X-Tenant-Id"]
        for _ in range(20):
            detect_body = client.post("/v1/detect", json=detect_payload, headers=valid_headers).json()
            if detect_body["anomalies_detected"] and detect_body["anomalies_list"]:
                anomaly_id = detect_body["anomalies_list"][0]["anomaly_id"]

                resp = client.get(f"/v1/status/{anomaly_id}", headers={"X-Tenant-Id": owner_tenant})
                assert resp.status_code == 200
                body = resp.json()

                assert body["anomaly_id"] == anomaly_id
                assert body["audit_id"] != anomaly_id
                assert "status" in body
                assert "containment_locked" in body
                assert "error_budget_remaining_pct" in body
                assert isinstance(body["actions_log"], list)
                return
        pytest.skip("No anomalies detected in 20 attempts (probabilistic mock)")
