# ADR 002: Gom storage và query vào Grafana LGTM Cloud

## Status
Accepted

## Context

On-call đang phải nhảy giữa Datadog, Splunk, PagerDuty. Splunk search latency làm chậm điều tra, còn UI phân mảnh làm MTTR cao.

## Decision

Chuyển metrics, logs và traces sang Grafana Mimir, Loki, Tempo và dùng Grafana Unified UI làm cổng truy cập chính.

## Rationale

1. Một UI giảm context switching.
2. Loki và Tempo được thiết kế cho chi phí thấp hơn lưu trữ/search kiểu cũ.
3. Grafana kết hợp tốt với Mimir/Loki/Tempo và hỗ trợ các ngôn ngữ query chuyên biệt.

## Alternatives Considered

| Option | Pros | Cons |
|---|---|---|
| Giữ Splunk + Datadog nhưng tối ưu dashboard | Ít rủi ro thay đổi | Không giải quyết gốc vấn đề về chi phí và latency |
| Dùng ELK tự quản | Chủ động hơn | Chi phí vận hành và search tuning tăng mạnh |

## Consequences

- **Positive**: giảm chi phí, giảm context switching, query nhanh hơn, vận hành tập trung hơn.
- **Negative**: team cần học PromQL, LogQL, TraceQL và có thể thiếu kinh nghiệm ban đầu.
- **Mitigation**: migration theo phase, cheat sheet truy vấn, pairing cho on-call, và giữ PagerDuty làm routing lớp cuối.

