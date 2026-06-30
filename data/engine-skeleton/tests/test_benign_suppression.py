"""
Benign workload suppression (contract §5.1 business_context).

A Finance-ticketed scheduled backup / weekly ETL produces a real cost+usage bump.
The cost-spike detectors must treat it as benign when the CDO sets the matching
business_context flag — this is the deterministic fix for the June T1/T3
false positives (cost-spike layer), while the tag-policy (untagged_spend) layer
is intentionally NOT suppressed.
"""

import pytest

from app.services.ml.statistical_detect_service import (
    _detect_sudden_spike,
    _detect_gradual_drift,
    _detect_runaway_usage,
    _detect_untagged_spend,
    _is_benign,
)

# Inputs that fire each cost-spike detector when no benign context is present.
SPIKE = dict(cost=500.0, rolling_avg=100.0, rolling_std=20.0, rolling_median=100.0, rolling_mad=10.0)
DRIFT = dict(slope_14d=2.0, cost_pct_change_28d=0.5)
RUNAWAY = dict(cost=500.0, cost_ratio=8.0, usage_density=0.99, cpu_mean=95.0)


class TestIsBenign:
    @pytest.mark.parametrize("flag", [
        "campaign_flag", "load_test_flag", "migration_flag",
        "scheduled_backup_flag", "batch_etl_flag",
    ])
    def test_each_flag_marks_benign(self, flag):
        assert _is_benign({flag: True}) is True

    def test_empty_and_none_not_benign(self):
        assert _is_benign({}) is False
        assert _is_benign(None) is False


class TestCostSpikeSuppression:
    def test_sudden_spike_fires_without_context(self):
        fired, *_ = _detect_sudden_spike(**SPIKE)
        assert fired is True

    def test_sudden_spike_suppressed_by_scheduled_backup(self):
        fired, *_ = _detect_sudden_spike(**SPIKE, business_context={"scheduled_backup_flag": True})
        assert fired is False

    def test_gradual_drift_fires_without_context(self):
        fired, *_ = _detect_gradual_drift(**DRIFT)
        assert fired is True

    def test_gradual_drift_suppressed_by_batch_etl(self):
        fired, *_ = _detect_gradual_drift(**DRIFT, business_context={"batch_etl_flag": True})
        assert fired is False

    def test_runaway_suppressed_by_scheduled_backup(self):
        fired, *_ = _detect_runaway_usage(**RUNAWAY, business_context={"scheduled_backup_flag": True})
        assert fired is False


class TestGovernanceLayerNotSuppressed:
    """Tag-policy is independent of why cost moved — scheduled_backup must NOT
    silence an untagged-spend (governance) flag, only campaign/load-test/migration do."""

    def test_untagged_fires_when_owner_missing(self):
        fired, *_ = _detect_untagged_spend(200.0, team_missing=False, owner_missing=True,
                                           product_code="AmazonRDS", business_context={})
        assert fired is True

    def test_untagged_NOT_suppressed_by_scheduled_backup(self):
        fired, *_ = _detect_untagged_spend(200.0, team_missing=True, owner_missing=True,
                                           product_code="AmazonRDS",
                                           business_context={"scheduled_backup_flag": True})
        assert fired is True

    def test_untagged_suppressed_by_migration(self):
        fired, *_ = _detect_untagged_spend(200.0, team_missing=True, owner_missing=True,
                                           product_code="AmazonRDS",
                                           business_context={"migration_flag": True})
        assert fired is False
