"""
TenantStateService — multi-tenant safety guard (contract §3.1, §3.2, §4).

Central authority for two cross-cutting concerns the contract requires but that
were previously unenforced:

  1. **Multi-tenant isolation** (§4 ``X-Tenant-Id``). An anomaly produced for one
     tenant must never be actioned by another. We keep an ownership registry
     ``anomaly_id -> (tenant_id, env)`` populated at /v1/detect time and consulted
     by /v1/decide, /v1/status and the rollback hook to raise
     ``403 ERR_CROSS_TENANT_DENIED``.

  2. **Error-budget LOCKED_MODE** (§3.2). Rollback (false-positive) rate is tracked
     per ``(tenant_id, env)`` over the 30-day window. When the burn crosses the
     per-environment threshold the tenant flips to LOCKED_MODE and every
     /v1/decide for that tenant+env is forced to dry-run only.

Production backs both stores with DynamoDB (`finops-error-budget-{env}`,
`finops-anomaly-ownership`). This in-process implementation is the dev/test
fallback — identical semantics, no AWS dependency.
"""

from __future__ import annotations

import threading

from app.config.settings import settings


_PROD_ENVS = {"prod", "prod-core", "prod-payments"}


ROLLBACK_BURN_PCT = 0.5


class TenantStateService:
    """Thread-safe per-tenant safety state (error budget + anomaly ownership)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._budget: dict[tuple[str, str], float] = {}
        self._ownership: dict[str, tuple[str, str]] = {}



    def register_anomaly(self, anomaly_id: str, tenant_id: str, env: str) -> None:
        """Record which tenant owns an anomaly (called once per detect result)."""
        with self._lock:
            self._ownership[anomaly_id] = (tenant_id, env)

    def owner_of(self, anomaly_id: str) -> str | None:
        rec = self._ownership.get(anomaly_id)
        return rec[0] if rec else None

    def env_of(self, anomaly_id: str, default: str = "prod") -> str:
        """Environment an anomaly belongs to; conservative default for unknown IDs."""
        rec = self._ownership.get(anomaly_id)
        return rec[1] if rec else default

    def is_cross_tenant(self, anomaly_id: str, tenant_id: str) -> bool:
        """
        True only when the anomaly is registered to a *different* tenant.

        Unknown anomaly IDs are intentionally allowed through (replayed/historical
        IDs, or IDs minted outside this process) — isolation only blocks proven
        cross-tenant access, never first-seen IDs.
        """
        owner = self.owner_of(anomaly_id)
        return owner is not None and owner != tenant_id



    @staticmethod
    def threshold(env: str) -> float:
        """Rollback-rate % at which the tenant+env flips to LOCKED_MODE."""
        if env in _PROD_ENVS:
            return settings.error_budget_lock_threshold_prod
        if env == "staging":
            return settings.error_budget_lock_threshold_staging
        return float("inf")

    def burned_pct(self, tenant_id: str, env: str) -> float:
        return self._budget.get((tenant_id, env), 0.0)

    def remaining_pct(self, tenant_id: str, env: str) -> float:
        """Budget remaining as 100 − burned, clamped to [0, 100] (§5.5 field)."""
        return round(max(0.0, 100.0 - self.burned_pct(tenant_id, env)), 1)

    def is_locked(self, tenant_id: str, env: str) -> bool:
        thr = self.threshold(env)
        return thr != float("inf") and self.burned_pct(tenant_id, env) >= thr

    def burn_rollback(self, tenant_id: str, env: str) -> tuple[float, bool]:
        """
        Apply one rollback's burn to (tenant_id, env).

        Returns (new_burned_pct, locked_now).
        """
        with self._lock:
            burned = round(self._budget.get((tenant_id, env), 0.0) + ROLLBACK_BURN_PCT, 2)
            self._budget[(tenant_id, env)] = burned
        return burned, self.is_locked(tenant_id, env)
