# ADR 001: Chuẩn hóa ingestion bằng OpenTelemetry Collector

## Status
Accepted

## Context

GeekShop đang dùng nhiều đường ingest rời rạc. Head-based sampling 1% làm mất trace quan trọng, trong khi custom metrics gây cardinality explosion ở backend.

## Decision

Chuẩn hóa toàn bộ telemetry vào OpenTelemetry SDK + OpenTelemetry Collector DaemonSet ở edge, bật tail-based sampling và label filtering trước khi export.

## Rationale

1. Collector là điểm trung lập với vendor, dễ export sang Mimir/Loki/Tempo.
2. Tail-based sampling giữ được trace quan trọng sau khi đã thấy kết quả request.
3. Label filtering ở edge chặn cardinality trước khi nó đi vào backend đắt tiền.

## Alternatives Considered

| Option | Pros | Cons |
|---|---|---|
| Giữ Datadog agent + Splunk forwarder | Ít thay đổi ngắn hạn | Vẫn phân mảnh, vẫn đắt, vẫn mất trace vì head sampling |
| Đẩy mọi thứ thẳng vào backend mà không có Collector | Ít thành phần | Không có điểm kiểm soát sampling/label, dễ quá tải và khó chuẩn hóa |

## Consequences

- **Positive**: giảm chi phí ingest, giảm mất tín hiệu trace, tạo một policy point duy nhất.
- **Negative**: Collector có thể OOM nếu tail sampling policy quá rộng hoặc buffer quá lớn.
- **Mitigation**: đặt memory limit, queue giới hạn, sampling policy theo criticality, và POC tải 5,000 req/s trước rollout rộng.

