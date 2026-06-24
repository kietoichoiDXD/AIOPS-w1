# Architecture Decision Records - Nhóm AI 2 (FinOps Watch)

<!-- Doc owner: Nhóm AI 2
     Status: Final W12
     Format: 1 ADR per major decision. Append-only - không xóa ADR cũ. -->

This document records the architectural decisions made by the AI Team for the FinOps Watch System.

---

## ADR-001 - Hybrid Architecture (Isolation Forest + Amazon Nova LLM)

- **Status**: Accepted
- **Date**: 2026-06-23
- **Context**: We need to detect cost anomalies and explain them in natural financial terms. A pure machine learning approach lacks explainability, while a pure LLM approach is too expensive (over the $50/month budget) and has high latency.
- **Decision**: We chose a hybrid architecture. First, a local Isolation Forest + Static Heuristics filter processes raw data to eliminate 95% of normal data points. Second, the remaining suspect anomalies are sent to AWS Bedrock using the `amazon.nova-pro-v1:0` model for Root Cause Analysis (RCA) and mitigation selection.
- **Consequence**:
  - ✅ High cost reduction (>95% token savings), keeping the monthly Bedrock cost under $15.
  - ✅ Rich natural language explanations (explainable decisions).
  - ⚠️ We depend on two different detection layers; if the local ML filter fails to flag an anomaly, the LLM will never see it.
- **Alternatives considered**:
  - *Option A: Pure LLM Ingestion*. Rejected due to high token cost (~$400/month) and high latency.
  - *Option B: Pure Machine Learning (Isolation Forest/Z-Score only)*. Rejected due to poor context understanding and zero explainability.

---

## ADR-002 - Scheduled Batch Ingestion with 24h Cadence (02:00 AM)

- **Status**: Accepted
- **Date**: 2026-06-23
- **Context**: Cost Explorer and AWS CUR data are updated by AWS with a natural lag of 8 to 24 hours. A real-time streaming pipeline would process incomplete data and trigger high false positives.
- **Decision**: We chose a scheduled batch ingestion pattern with a 24-hour cadence, triggered at 02:00 AM daily. If data lag is detected, the CDO Platform sends a `telemetry_delay_event` to suspend execution, retry hourly, and ensure baseline stability.
- **Consequence**:
  - ✅ Highly stable baseline and minimal false positive rate (FPR <= 10%).
  - ✅ Simplifies operations and reduces Bedrock query costs.
  - ⚠️ Maximum time-to-detect is 24 hours. A runaway GPU cluster could burn up to $400 before containment.
- **Alternatives considered**:
  - *Option A: 12-hour cadence*. Rejected due to high data lag issues from AWS causing false spikes (estimated vs finalized data conflict).
  - *Option B: 48-hour cadence*. Rejected because the detection lag is too long, causing significant waste.

---

## ADR-003 - DynamoDB Caching for Cost Explorer API Results

- **Status**: Accepted
- **Date**: 2026-06-24
- **Context**: The AWS Cost Explorer API has a strict rate limit of 5 requests per second. Repeated calls for historical baseline calculations can lead to throttling.
- **Decision**: We chose to cache Cost Explorer daily aggregates in Amazon DynamoDB with a TTL of 7 days for hot data, and archive them in S3 for historical analysis. The AI Engine reads from the cache rather than querying the Cost Explorer API directly.
- **Consequence**:
  - ✅ Avoids AWS API rate-limiting issues.
  - ✅ Reduces overall API latency to < 10ms for historical baseline retrievals.
  - ⚠️ Increases storage cost slightly (~$1.00/month for DynamoDB).
- **Alternatives considered**:
  - *Option A: Direct API calling*. Rejected because of AWS throttling risks.
  - *Option B: S3 storage only*. Rejected because S3 retrieval latency is too high for interactive dashboards.

---

## ADR-004 - AWS IAM SigV4 Authentication for Inter-Service Calls

- **Status**: Accepted
- **Date**: 2026-06-24
- **Context**: Inter-service communication between the CDO Platform and the AI Engine must be secure. Static API keys are vulnerable to leakage and require manual rotation.
- **Decision**: We enforce AWS IAM SigV4 signing for all incoming requests to the `/v1/detect` and action endpoints. No static API keys or long-lived credentials are allowed.
- **Consequence**:
  - ✅ Maximum security, aligning with AWS best practices.
  - ✅ Automatic credential rotation.
  - ⚠️ Requires the CDO team to implement SigV4 signing logic in their API client.
- **Alternatives considered**:
  - *Option A: Static API Keys in Secrets Manager*. Rejected because it still introduces static secret risks in code.
  - *Option B: Basic Auth*. Rejected as insecure for production.

---

## ADR-005 - 1% Error Budget Lock for Auto-Containment Actions

- **Status**: Accepted
- **Date**: 2026-06-24
- **Context**: Auto-containment (like stop EC2 or stop SageMaker) in dev/ML-research environments runs without human intervention. If the AI model starts misclassifying normal workloads as anomalies, it can disrupt engineering operations.
- **Decision**: We implemented a 1% Error Budget Lock. If the user undo/rollback rate exceeds 1% within a sliding 30-day window, the system automatically locks containment actions to `Dry-run / Alert-only` mode and triggers a P1 SRE alert.
- **Consequence**:
  - ✅ Protects developer operations and trust.
  - ✅ Prevents runaway automated actions during concept drift.
  - ⚠️ Legitimate containment actions might get blocked until SRE resets the budget lock.
- **Alternatives considered**:
  - *Option A: No auto-lock*. Rejected due to high operational risk of unchecked automation.
  - *Option B: Direct human approval for every dev action*. Rejected because it defeats the goal of automated cost containment.
