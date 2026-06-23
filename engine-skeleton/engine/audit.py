"""
Audit trail logger.
====================
Writes immutable audit entries for every detection + containment decision.
SOC2 requires: actor, before/after state, rollback path, retention ≥ 90 days.

Skeleton: logs to stdout as structured JSON.
Production: replace with S3/DynamoDB writer via adapter pattern.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID, uuid4

from models.domain import AnomalyResult, AuditEntry, ContainmentDecision

logger = logging.getLogger("finops-engine.audit")


class AuditLogger:
    """
    Audit trail writer.
    Skeleton implementation logs to structured stdout.
    W12 production: swap to S3 + DynamoDB adapter.
    """

    def create_audit_entry(
        self,
        tenant_id: str,
        correlation_id: Optional[str],
        detection_result: AnomalyResult,
        containment_decision: Optional[ContainmentDecision] = None,
    ) -> AuditEntry:
        """Create and persist an audit entry. Returns the entry with generated audit_id."""
        entry = AuditEntry(
            audit_id=uuid4(),
            timestamp=datetime.now(timezone.utc),
            tenant_id=tenant_id,
            correlation_id=correlation_id,
            detection_result=detection_result,
            containment_decision=containment_decision,
            actor="ai-engine-skeleton",
        )

        self._persist(entry)
        return entry

    def _persist(self, entry: AuditEntry) -> None:
        """
        Write audit entry to persistent store.

        Skeleton: structured log to stdout (CloudWatch Logs captures this).
        W12 TODO: write to DynamoDB (pk=tenant_id, sk=audit_id) + S3 archive.
        """
        audit_record = {
            "audit_id": str(entry.audit_id),
            "timestamp": entry.timestamp.isoformat(),
            "tenant_id": entry.tenant_id,
            "correlation_id": entry.correlation_id,
            "is_anomaly": entry.detection_result.is_anomaly,
            "anomaly_type": entry.detection_result.anomaly_type.value if entry.detection_result.is_anomaly else None,
            "severity": entry.detection_result.severity,
            "confidence": entry.detection_result.confidence,
            "reasoning": entry.detection_result.reasoning,
            "containment_action": (
                entry.containment_decision.action.value
                if entry.containment_decision
                else None
            ),
            "containment_status": (
                entry.containment_decision.status.value
                if entry.containment_decision
                else None
            ),
            "actor": entry.actor,
        }

        logger.info("AUDIT_TRAIL | %s", json.dumps(audit_record, ensure_ascii=False))


# Module-level singleton
audit_logger = AuditLogger()
