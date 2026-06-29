"""
Abstract service interfaces.

Production implementations (Isolation Forest, RCF, Nova) must inherit
from these classes and implement the same method signatures. The mock
layer and the real layer are fully interchangeable without touching
router or schema code.
"""

from abc import ABC, abstractmethod

from app.schemas.detect import DetectRequest, DetectResponse
from app.schemas.decide import DecideRequest, DecideResponse
from app.schemas.verify import VerifyRequest, VerifyResponse
from app.schemas.status import RemediationStatusResponse, RollbackRequest, RollbackResponse


class DetectService(ABC):
    """Interface for the anomaly detection engine."""

    @abstractmethod
    def detect(self, request: DetectRequest, correlation_id: str) -> DetectResponse:
        """
        Analyse CUR / CE telemetry and return a list of detected anomalies.

        Production implementation will call:
          - Isolation Forest (primary)
          - Random Cut Forest (benchmark)
          - Amazon Nova (explanation generation)
        """

    @abstractmethod
    def get_status(self, anomaly_id: str) -> RemediationStatusResponse | None:
        """Return current remediation status for a given anomaly_id."""


class DecisionService(ABC):
    """Interface for the containment decision and verification engine."""

    @abstractmethod
    def decide(self, request: DecideRequest) -> DecideResponse:
        """
        Given an anomaly context, return a containment action plan with AWS CLI
        payloads and dashboard data.

        Production implementation will:
          - Match runbook from library
          - Generate AWS CLI commands via boto3
          - Call Amazon Nova for executive summary
          - Write audit trail to DynamoDB
        """

    @abstractmethod
    def verify(self, request: VerifyRequest) -> VerifyResponse:
        """
        Evaluate post-action telemetry and decide DONE / RETRY / ROLLBACK / ESCALATE.
        """

    @abstractmethod
    def record_rollback(self, audit_id: str, request: RollbackRequest) -> RollbackResponse:
        """
        Record a manual rollback (false-positive feedback) and update error budget.
        """
