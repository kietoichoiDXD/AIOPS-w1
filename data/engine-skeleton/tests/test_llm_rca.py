"""
Tests for the offline (deterministic) path of the LLM RCA module.

These run with RCA_MODE=offline so no AWS / Bedrock calls are made — they verify
the deterministic engine that backs both CI/grading and the Bedrock-failure
fallback, plus the prod safety clamp in decide().
"""

import os

import pytest

# Force the deterministic, network-free engine for this whole module.
os.environ["RCA_MODE"] = "offline"
os.environ.pop("BEDROCK_MOCK", None)

from app.models.enums import AnomalyType  # noqa: E402
from app.services.ml import llm_rca  # noqa: E402


def _record(**overrides) -> dict:
    base = {
        "resource_id": "i-0abcd1234efgh5678",
        "environment": "ml-research",
        "confidence_score": 0.92,
        "line_item_product_code": "AmazonEC2",
        "line_item_unblended_cost": 427.50,
        "cost_ratio_to_7d_avg": 18.2,
        "usage_density_24h": 0.98,
        "cpu_mean": 91.0,
        "resource_tags_user_owner": "dev@company.com",
        "resource_tags_user_team": "squad-ml-core",
        "absolute_cost_spike": 300.0,
        "driver_feature": "usage_density_24h",
    }
    base.update(overrides)
    return base


class TestOfflineRcaShape:
    def test_returns_all_rich_fields(self):
        rca = llm_rca.analyze_root_cause(_record(), AnomalyType.runaway_usage, "usage_density_24h")
        for field in (
            "primary_driver_feature",
            "root_cause_category",
            "finance_summary",
            "technical_reason",
            "missing_mandatory_tags",
            "risk_level",
        ):
            assert field in rca, f"missing {field}"

    def test_driver_feature_echoed(self):
        rca = llm_rca.analyze_root_cause(_record(), AnomalyType.idle_resource, "usage_density_24h")
        assert rca["primary_driver_feature"] == "usage_density_24h"

    def test_category_maps_from_anomaly_type(self):
        cases = {
            AnomalyType.idle_resource: "Idle Resource",
            AnomalyType.untagged_spend: "Mis-tagged Spend",
            AnomalyType.sudden_spike: "Cost Spike",
            AnomalyType.runaway_usage: "Runaway Job",
            AnomalyType.gradual_drift: "Cost Drift",
        }
        for atype, expected in cases.items():
            rca = llm_rca.analyze_root_cause(_record(), atype, "usage_density_24h")
            assert rca["root_cause_category"] == expected

    def test_technical_reason_uses_driver_specific_text(self):
        rca = llm_rca.analyze_root_cause(_record(), AnomalyType.idle_resource, "usage_density_24h")
        assert "usage_density_24h" in rca["technical_reason"]

    def test_finance_summary_has_numbers(self):
        rca = llm_rca.analyze_root_cause(_record(), AnomalyType.runaway_usage, "usage_density_24h")
        assert "427.50" in rca["finance_summary"]
        assert "12,825.00" in rca["finance_summary"]  # 427.50 * 30


class TestTagPolicy:
    def test_missing_owner_flagged_and_risk_high(self):
        rec = _record(resource_tags_user_owner=None)
        rca = llm_rca.analyze_root_cause(rec, AnomalyType.idle_resource, "usage_density_24h")
        assert "resource_tags_user_owner" in rca["missing_mandatory_tags"]
        assert rca["risk_level"] in ("High", "Critical")

    def test_missing_sentinel_strings_detected(self):
        for sentinel in ("", "  ", "nan", "MISSING", "None"):
            rec = _record(resource_tags_user_team=sentinel)
            tags = llm_rca.missing_mandatory_tags(rec)
            assert "resource_tags_user_team" in tags

    def test_present_tags_not_flagged(self):
        rca = llm_rca.analyze_root_cause(_record(), AnomalyType.sudden_spike, "cost_ratio_to_7d_avg")
        assert rca["missing_mandatory_tags"] == []


class TestRiskEscalation:
    def test_high_cost_escalates_to_critical(self):
        rec = _record(line_item_unblended_cost=1500.0)
        rca = llm_rca.analyze_root_cause(rec, AnomalyType.gradual_drift, "slope_14d")
        assert rca["risk_level"] == "Critical"

    def test_low_cost_drift_stays_low(self):
        rec = _record(line_item_unblended_cost=12.0, cost_ratio_to_7d_avg=1.4, absolute_cost_spike=0.0)
        rca = llm_rca.analyze_root_cause(rec, AnomalyType.gradual_drift, "slope_14d")
        assert rca["risk_level"] == "Low"


class TestMitigationOffline:
    def test_recommend_mitigation_is_none_offline(self):
        """Offline mode defers to the deterministic env matrix in decide()."""
        assert llm_rca.recommend_mitigation(_record(), {"root_cause_category": "Runaway Job"}) is None
