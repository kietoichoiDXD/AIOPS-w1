"""
W12 T2 — Safety guard (error-budget LOCKED_MODE, §3.2) + multi-tenant routing (§4).

Covers:
  - X-Tenant-Id UUID-shape validation.
  - Cross-tenant isolation: anomaly owned by tenant A cannot be actioned/polled by B.
  - Error-budget burn lowers remaining %; crossing the prod threshold flips LOCKED_MODE.
  - LOCKED_MODE forces /v1/decide to dry-run + tag-for-review only, with the
    X-Containment-Status: LOCKED response header.
"""

import datetime
import uuid

import pytest

from app.models.enums import AnomalyType, AppliedActionType, ContainmentAction, Environment
from app.schemas.decide import AnomalyContext, DecideRequest
from app.services.ml.decision_service import ProductionDecisionService
from app.services.ml.statistical_detect_service import StatisticalDetectService
from app.services.ml.tenant_state import TenantStateService
from app.services.rate_limiter import RateLimiter


def _headers(tenant_id: str, dry_run: str = "true") -> dict:
    return {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "X-Tenant-Id": tenant_id,
        "X-Idempotency-Key": f"{tenant_id}:2026-06-29:daily-batch",
        "X-Payload-SHA256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
        "X-Request-Timestamp": datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "X-Dry-Run-Mode": dry_run,
        "X-Correlation-Id": "9b1deb4d-3b7d-4bad-9bdd-2b0d7b3dcb6d",
    }


def _decide_payload(anomaly_id: str, env: str, dry_run: bool = True) -> dict:
    return {
        "correlation_id": "9b1deb4d-3b7d-4bad-9bdd-2b0d7b3dcb6d",
        "idempotency_key": "a1b2c3d4-e5f6-7890-abcd-ef1234567890:2026-06-29:daily-batch",
        "dry_run_mode": dry_run,
        "anomaly_context": {
            "anomaly_id": anomaly_id,
            "anomaly_type": "runaway_usage",
            "resource_id": "i-0abcd1234efgh5678",
            "environment": env,
            "unblended_cost_24h_usd": 427.50,
            "cost_ratio_to_7d_avg": 18.2,
            "responsible_team": "squad-ml-core",
        },
    }




class TestTenantValidation:
    def test_non_uuid_tenant_rejected(self, client, decide_payload):
        h = _headers("not-a-uuid")
        resp = client.post("/v1/decide", json=decide_payload, headers=h)
        assert resp.status_code == 400
        assert resp.json()["error_code"] == "ERR_INVALID_SCHEMA"

    def test_uuid_shape_tenant_accepted(self, client):
        h = _headers(str(uuid.uuid4()))
        resp = client.post("/v1/decide", json=_decide_payload("ANM-2030-0101A", "ml-research"), headers=h)
        assert resp.status_code == 200




class TestCrossTenantIsolation:
    def test_decide_blocked_for_foreign_tenant(self, client, detect_payload):
        tenant_a = str(uuid.uuid4())
        tenant_b = str(uuid.uuid4())


        anomaly_id = None
        for _ in range(20):
            body = client.post("/v1/detect", json=detect_payload, headers=_headers(tenant_a)).json()
            if body["anomalies_detected"] and body["anomalies_list"]:
                anomaly_id = body["anomalies_list"][0]["anomaly_id"]
                break
        assert anomaly_id, "detect did not produce an anomaly to own"


        resp = client.post(
            "/v1/decide",
            json=_decide_payload(anomaly_id, "ml-research"),
            headers=_headers(tenant_b),
        )
        assert resp.status_code == 403
        assert resp.json()["error_code"] == "ERR_CROSS_TENANT_DENIED"


        resp_a = client.post(
            "/v1/decide",
            json=_decide_payload(anomaly_id, "ml-research"),
            headers=_headers(tenant_a),
        )
        assert resp_a.status_code == 200

    def test_status_blocked_for_foreign_tenant(self, client, detect_payload):
        tenant_a = str(uuid.uuid4())
        tenant_b = str(uuid.uuid4())
        anomaly_id = None
        for _ in range(20):
            body = client.post("/v1/detect", json=detect_payload, headers=_headers(tenant_a)).json()
            if body["anomalies_detected"] and body["anomalies_list"]:
                anomaly_id = body["anomalies_list"][0]["anomaly_id"]
                break
        assert anomaly_id

        resp = client.get(f"/v1/status/{anomaly_id}", headers={"X-Tenant-Id": tenant_b})
        assert resp.status_code == 403
        assert resp.json()["error_code"] == "ERR_CROSS_TENANT_DENIED"

    def test_unknown_anomaly_not_blocked(self, client):
        """First-seen / historical anomaly IDs pass isolation (no proven owner)."""
        resp = client.post(
            "/v1/decide",
            json=_decide_payload("ANM-2030-0101Z", "ml-research"),
            headers=_headers(str(uuid.uuid4())),
        )
        assert resp.status_code == 200




class TestErrorBudgetLock:
    def test_rollback_burns_budget(self, client):
        tenant = str(uuid.uuid4())
        body = client.post(
            "/v1/audit/ANM-2030-0101A/rollback",
            json={"reason": "FP", "rolled_back_by": "e@c.com"},
            headers=_headers(tenant),
        ).json()
        assert body["new_error_budget_burned_pct"] == pytest.approx(0.5)
        assert body["containment_locked"] is False

    def test_prod_locks_after_threshold(self, client):
        tenant = str(uuid.uuid4())

        client.post("/v1/audit/ANM-2030-0101B/rollback",
                    json={"reason": "FP", "rolled_back_by": "e@c.com"}, headers=_headers(tenant))
        second = client.post("/v1/audit/ANM-2030-0101B/rollback",
                             json={"reason": "FP", "rolled_back_by": "e@c.com"}, headers=_headers(tenant)).json()
        assert second["containment_locked"] is True


        resp = client.post(
            "/v1/decide",
            json=_decide_payload("ANM-2030-0101C", "prod", dry_run=False),
            headers=_headers(tenant, dry_run="false"),
        )
        assert resp.status_code == 200
        assert resp.headers.get("X-Containment-Status") == "LOCKED"
        assert resp.json()["dry_run_mode"] is True




class TestRateLimit:
    def test_unit_limiter_blocks_over_limit(self):
        rl = RateLimiter(max_per_min=3)
        t = "tenant-x"
        assert all(rl.allow(t)[0] for _ in range(3))
        allowed, retry_after = rl.allow(t)
        assert allowed is False
        assert retry_after >= 1

        assert rl.allow("tenant-y")[0] is True

    def test_unit_limiter_disabled_when_zero(self):
        rl = RateLimiter(max_per_min=0)
        assert all(rl.allow("t")[0] for _ in range(1000))

    def test_api_returns_429_with_retry_after(self, client, decide_payload):
        tenant = str(uuid.uuid4())
        original = client.app.state.rate_limiter
        client.app.state.rate_limiter = RateLimiter(max_per_min=2)
        try:
            h = _headers(tenant)
            codes = [
                client.post("/v1/decide", json=_decide_payload("ANM-2030-0101A", "ml-research"), headers=h).status_code
                for _ in range(3)
            ]
            assert codes[0] == 200 and codes[1] == 200
            assert codes[2] == 429
            last = client.post("/v1/decide", json=_decide_payload("ANM-2030-0101A", "ml-research"), headers=h)
            assert last.json()["error_code"] == "ERR_RATE_LIMITED"
            assert int(last.headers["Retry-After"]) >= 1
        finally:
            client.app.state.rate_limiter = original




class TestLockedDowngrade:
    def test_locked_downgrades_dev_action_to_tag_only(self):
        """A normally auto-shutdown dev env is downgraded to tag-for-review when locked."""
        ts = TenantStateService()
        svc = ProductionDecisionService(detect_service=StatisticalDetectService(), tenant_state=ts)
        req = DecideRequest(
            correlation_id="9b1deb4d-3b7d-4bad-9bdd-2b0d7b3dcb6d",
            idempotency_key="a1b2c3d4-e5f6-7890-abcd-ef1234567890:2026-06-29:daily-batch",
            dry_run_mode=False,
            anomaly_context=AnomalyContext(
                anomaly_id="ANM-2030-0101D",
                anomaly_type=AnomalyType.sudden_spike,
                resource_id="i-0dev123",
                environment=Environment("dev"),
                unblended_cost_24h_usd=200.0,
                cost_ratio_to_7d_avg=12.0,
            ),
        )


        unlocked = svc.decide(req, locked=False)
        assert any(s.action == ContainmentAction.auto_shutdown for s in unlocked.action_plan)
        assert unlocked.dry_run_mode is False


        locked = svc.decide(req, locked=True)
        assert all(s.action == ContainmentAction.tag_for_review for s in locked.action_plan)
        assert locked.dry_run_mode is True
        assert locked.applied_payload.action_type == AppliedActionType.inject_aws_tag
