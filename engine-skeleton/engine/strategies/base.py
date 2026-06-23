"""
Detection strategy interface (Strategy Pattern).
==================================================
All detection algorithms implement this ABC.
Swap strategies via config or feature flag — no code change in router.

W11 skeleton: DummyStrategy (hardcoded responses)
W12 real:     StatisticalStrategy / LLMStrategy (plug in seamlessly)
Curveball:    CompositeStrategy (chain multiple strategies)
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import List, Optional

from api.schemas.detect import DetectRequest, CostWindowItem, BaselineMetadata
from models.domain import AnomalyResult


class DetectionStrategy(ABC):
    """Abstract base for all anomaly detection strategies."""

    @abstractmethod
    def detect(
        self,
        cost_window: List[CostWindowItem],
        baseline: Optional[BaselineMetadata],
        tenant_id: str,
    ) -> AnomalyResult:
        """
        Analyse cost data and return an anomaly result.

        Args:
            cost_window: Current cost data points to analyse.
            baseline: Historical baseline metadata for comparison.
            tenant_id: Tenant identifier for multi-tenant isolation.

        Returns:
            AnomalyResult with detection findings.
        """
        ...

    @property
    @abstractmethod
    def strategy_name(self) -> str:
        """Human-readable name for audit logging."""
        ...
