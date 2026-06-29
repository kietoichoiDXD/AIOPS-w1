"""Tests for POST /v1/decide and POST /v1/audit/{audit_id}/rollback."""

import pytest
from fastapi.testclient import TestClient

PROD_ENVS = ["prod", "prod-core", "prod-payments"]
NON_PROD_ENVS = ["staging", "dev", "sandbox", "ml-research", "data-analytics"]


class TestDecideSuccess:
    def test_returns_200(self, client, valid_headers, decide_payload):
        resp = client.post("/v1/decide", json=decide_payload, headers=valid_headers)
        assert resp.status_code == 200

    def test_response_has_all_required_fields(self, client, valid_headers, decide_payload):
        body = client.post("/v1/decide", json=decide_payload, headers=valid_headers).json()
        for field in [
            "matched_runbook",
            "action_plan",
            "applied_payload",
            "rollback_payload",
            "finance_dashboard_data",
            "engineering_dashboard_data",
            "correlation_id",
            "dry_run_mode",
        ]:
            assert field in body, f"Missing field: {field}"

    def test_correlation_id_echoed(self, client, valid_headers, decide_payload):
        body = client.post("/v1/decide", json=decide_payload, headers=valid_headers).json()
        assert body["correlation_id"] == decide_payload["correlation_id"]

    def test_dry_run_mode_echoed(self, client, valid_headers, decide_payload):
        body = client.post("/v1/decide", json=decide_payload, headers=valid_headers).json()
        assert body["dry_run_mode"] == decide_payload["dry_run_mode"]

    def test_action_plan_is_list(self, client, valid_headers, decide_payload):
        body = client.post("/v1/decide", json=decide_payload, headers=valid_headers).json()
        assert isinstance(body["action_plan"], list)
        assert len(body["action_plan"]) >= 1

    def test_action_plan_steps_sequential(self, client, valid_headers, decide_payload):
        body = client.post("/v1/decide", json=decide_payload, headers=valid_headers).json()
        steps = [s["step"] for s in body["action_plan"]]
        assert steps == list(range(1, len(steps) + 1))

    def test_applied_payload_has_cli_command(self, client, valid_headers, decide_payload):
        body = client.post("/v1/decide", json=decide_payload, headers=valid_headers).json()
        assert body["applied_payload"]["aws_cli_command"].startswith("aws ")

    def test_rollback_payload_has_resource_id(self, client, valid_headers, decide_payload):
        body = client.post("/v1/decide", json=decide_payload, headers=valid_headers).json()
        assert body["rollback_payload"]["original_resource_id"] == "i-0abcd1234efgh5678"

    def test_finance_dashboard_has_metrics(self, client, valid_headers, decide_payload):
        body = client.post("/v1/decide", json=decide_payload, headers=valid_headers).json()
        metrics = body["finance_dashboard_data"]["metrics"]
        assert metrics["unblended_cost_24h_usd"] == pytest.approx(427.50)
        assert metrics["projected_monthly_waste_usd"] == pytest.approx(427.50 * 30, rel=0.01)

    def test_engineering_dashboard_has_rca(self, client, valid_headers, decide_payload):
        body = client.post("/v1/decide", json=decide_payload, headers=valid_headers).json()
        rca = body["engineering_dashboard_data"]["root_cause_analysis"]
        assert "primary_driver_feature" in rca
        assert "technical_reason" in rca

    def test_prod_env_uses_only_tag_for_review(self, client, valid_headers):
        """Hard boundary: prod environments must never get auto-shutdown."""
        for env in PROD_ENVS:
            payload = {
                "correlation_id": "9b1deb4d-3b7d-4bad-9bdd-2b0d7b3dcb6d",
                "idempotency_key": "a1b2c3d4-e5f6-7890-abcd-ef1234567890:2026-06-26:daily-batch",
                "dry_run_mode": True,
                "anomaly_context": {
                    "anomaly_id": "ANM-2026-0626A",
                    "anomaly_type": "runaway_usage",
                    "resource_id": "i-0abcd1234efgh5678",
                    "environment": env,
                    "unblended_cost_24h_usd": 427.50,
                    "cost_ratio_to_7d_avg": 18.2,
                    "responsible_team": "squad-prod",
                },
            }
            body = client.post("/v1/decide", json=payload, headers=valid_headers).json()
            actions = [s["action"] for s in body["action_plan"]]
            assert "auto-shutdown" not in actions, f"auto-shutdown in prod env {env}"
            assert "quota-cap" not in actions, f"quota-cap in prod env {env}"
            assert actions[0] == "tag-for-review"

    def test_dev_env_allows_auto_shutdown(self, client, valid_headers):
        payload = {
            "correlation_id": "9b1deb4d-3b7d-4bad-9bdd-2b0d7b3dcb6d",
            "idempotency_key": "a1b2c3d4-e5f6-7890-abcd-ef1234567890:2026-06-26:daily-batch",
            "dry_run_mode": True,
            "anomaly_context": {
                "anomaly_id": "ANM-2026-0626B",
                "anomaly_type": "sudden_spike",
                "resource_id": "i-0devinstance123",
                "environment": "dev",
                "unblended_cost_24h_usd": 200.0,
                "cost_ratio_to_7d_avg": 12.0,
                "responsible_team": "squad-backend",
            },
        }
        body = client.post("/v1/decide", json=payload, headers=valid_headers).json()
        actions = [s["action"] for s in body["action_plan"]]
        assert "auto-shutdown" in actions


class TestDecideValidation:
    def test_missing_headers_returns_400(self, client, decide_payload):
        resp = client.post("/v1/decide", json=decide_payload, headers={"Content-Type": "application/json"})
        assert resp.status_code == 400

    def test_missing_correlation_id_returns_400(self, client, valid_headers):
        payload = {
            "idempotency_key": "a1b2c3d4-e5f6-7890-abcd-ef1234567890:2026-06-26:daily-batch",
            "dry_run_mode": True,
            "anomaly_context": {
                "anomaly_id": "ANM-2026-0626A",
                "anomaly_type": "runaway_usage",
                "resource_id": "i-0abc",
                "environment": "dev",
                "unblended_cost_24h_usd": 100.0,
                "cost_ratio_to_7d_avg": 5.0,
                "responsible_team": "squad-test",
            },
        }
        resp = client.post("/v1/decide", json=payload, headers=valid_headers)
        assert resp.status_code == 400

    def test_invalid_idempotency_key_format_returns_400(self, client, valid_headers, decide_payload):
        bad_payload = dict(decide_payload)
        bad_payload["idempotency_key"] = "not-a-valid-key"
        resp = client.post("/v1/decide", json=bad_payload, headers=valid_headers)
        assert resp.status_code == 400

    def test_invalid_environment_enum_returns_400(self, client, valid_headers, decide_payload):
        bad_payload = dict(decide_payload)
        bad_payload["anomaly_context"] = dict(decide_payload["anomaly_context"])
        bad_payload["anomaly_context"]["environment"] = "production"
        resp = client.post("/v1/decide", json=bad_payload, headers=valid_headers)
        assert resp.status_code == 400


class TestRollback:
    def test_rollback_valid_returns_200(self, client, valid_headers):
        payload = {
            "reason": "False positive — experiment was approved",
            "rolled_back_by": "engineer@company.com",
        }
        resp = client.post("/v1/audit/ANM-2026-0626A/rollback", json=payload, headers=valid_headers)
        assert resp.status_code == 200

    def test_rollback_response_fields(self, client, valid_headers):
        payload = {"reason": "False positive", "rolled_back_by": "dev@company.com"}
        body = client.post("/v1/audit/ANM-2026-0626A/rollback", json=payload, headers=valid_headers).json()
        assert body["rollback_recorded"] is True
        assert body["false_positive_count_updated"] is True
        assert "new_error_budget_burned_pct" in body
        assert "containment_locked" in body
        assert "message" in body

    def test_invalid_audit_id_format_returns_400(self, client, valid_headers):
        payload = {"reason": "test", "rolled_back_by": "test@company.com"}
        resp = client.post("/v1/audit/INVALID-ID/rollback", json=payload, headers=valid_headers)
        assert resp.status_code == 400
