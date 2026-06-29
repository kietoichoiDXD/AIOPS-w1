"""
RateLimiter — per-tenant request throttle (contract §3: 100 req/min per tenant).

Fixed-window counter keyed by (tenant_id, minute-bucket). Production fronts the
engine with an Internal ALB / API Gateway usage plan; this in-process limiter is
defence-in-depth so a single misbehaving tenant cannot exhaust the engine even if
the edge limit is misconfigured.

``max_per_min <= 0`` disables limiting (used by the test suite).
"""

from __future__ import annotations

import threading
import time


class RateLimiter:
    def __init__(self, max_per_min: int) -> None:
        self.max_per_min = max_per_min
        self._lock = threading.Lock()
        self._buckets: dict[tuple[str, int], int] = {}

    def allow(self, tenant_id: str) -> tuple[bool, int]:
        """
        Register one request for ``tenant_id``.

        Returns ``(allowed, retry_after_seconds)``. ``retry_after_seconds`` is the
        whole seconds until the current minute window rolls over (≥1) when denied.
        """
        if self.max_per_min <= 0:
            return True, 0

        now = time.time()
        window = int(now // 60)
        key = (tenant_id, window)

        with self._lock:
            count = self._buckets.get(key, 0) + 1
            self._buckets[key] = count

            if len(self._buckets) > 10_000:
                self._buckets = {
                    k: v for k, v in self._buckets.items() if k[1] >= window
                }

        if count <= self.max_per_min:
            return True, 0
        retry_after = int((window + 1) * 60 - now)
        return False, max(retry_after, 1)
