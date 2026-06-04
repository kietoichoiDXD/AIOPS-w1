# FINDINGS — ShopX Incident Triage

## WHEN

- `cart-service` đã có tín hiệu log bất thường sớm từ `2026-06-01 06:32:33Z` với pattern `ProductCatalogCache eviction failed: heap pressure too high`.
- Z-score point-wise trên memory cho thấy điểm lệch đầu tiên từ `2026-06-01 08:07:30Z`, còn GC bắt đầu lệch rõ từ `2026-06-01 09:22:00Z`.
- Tín hiệu bền vững hơn xuất hiện từ `2026-06-01 16:20:30Z` khi memory giữ trạng thái tăng bất thường qua nhiều điểm liên tiếp.
- `jvm_gc_pause_ms_avg` tạo anomaly bền vững hơn từ `2026-06-01 17:24:30Z`.
- `memory_usage_bytes` đi vào vùng nguy hiểm hơn từ `2026-06-01 18:03:30Z` và đạt p99 từ `2026-06-01 19:38:00Z`.
- Hard failure xuất hiện vào `2026-06-01 19:59:00Z` với `OutOfMemoryError imminent: available heap < 5%` và `2026-06-01 19:59:02Z` với `Container OOMKilled: memory limit exceeded`.

## WHERE

### Metric signal sớm nhất

- Tín hiệu sớm nhưng chưa bền vững: `memory_usage_bytes` và `jvm_gc_pause_ms_avg` đều lệch trước khi incident thật sự nổ.
- Tín hiệu có độ tin cậy cao hơn là **sustained anomaly** trên `memory_usage_bytes` và `jvm_gc_pause_ms_avg`.
- `api-gateway` bắt đầu thấy `cart_upstream_error_rate` tăng có ý nghĩa từ khoảng `2026-06-01 20:00:30Z`.
- `order-service` thấy `upstream_timeout_rate` tăng mạnh từ khoảng `2026-06-01 20:32:00Z`.
- `payment-service` thấy `upstream_timeout_rate` tăng mạnh từ khoảng `2026-06-01 20:45:00Z`.

### Log signal sớm nhất

- Templated log sớm nhất liên quan trực tiếp đến lỗi là `ProductCatalogCache eviction failed: heap pressure too high`.
- `GC overhead limit warning: pause=... heap=...%` bắt đầu xuất hiện từ `2026-06-01 06:38:50Z`.
- Các pattern tiếp theo củng cố giả thuyết memory pressure:
  - `Connection pool nearing limit pool=db connections=50/50`
  - `OutOfMemoryError imminent: available heap < 5%`
  - `Container OOMKilled: memory limit exceeded`

## WHAT

### Root cause hypothesis

`cart-service` có khả năng bị memory pressure kéo dài do cache tăng quá mức hoặc cache eviction hoạt động kém hiệu quả, dẫn đến heap pressure tăng dần.

### Failure mechanism

1. Heap pressure tăng dần trong `cart-service`.
2. JVM GC phải chạy ngày càng nặng, làm `jvm_gc_pause_ms_avg` tăng.
3. GC pause và memory pressure làm `http_p99_latency_ms` tăng.
4. Khi heap tiến sát giới hạn 2 GB, pod bị `OOMKilled`.
5. Pod restart, hệ thống hồi tạm thời rồi lặp lại, tạo restart loop.
6. Upstream `api-gateway`, `order-service`, và `payment-service` bắt đầu timeout do phụ thuộc vào `cart-service`.

### Evidence summary

- `ProductCatalogCache eviction failed: heap pressure too high` xuất hiện từ `2026-06-01 16:00:01Z`.
- `jvm_gc_pause_ms_avg` anomaly bền vững từ `2026-06-01 17:24:30Z`.
- `memory_usage_bytes` đạt vùng nguy hiểm từ `2026-06-01 18:03:30Z`.
- `OutOfMemoryError imminent` và `Container OOMKilled` xuất hiện ngay tại `2026-06-01 19:59:00Z`.
- `container_restart_count` lên đến `7` vào `2026-06-01 23:43:00Z`.

## Methodology

- Z-score trên baseline đầu ngày để xác định anomaly sớm.
- Isolation Forest trên feature set của `cart-service` để dò bất thường đa biến.
- Regex template extraction cho log JSONL để gom pattern lặp lại.
- Trace correlation theo `trace_id` được dùng trong từng service log để theo dõi request journey trong cùng service, nhưng dữ liệu hiện tại không có trace_id chung xuyên suốt giữa `cart-service` và `order-service`.
- Phân tích cascade giữa services được chứng minh tốt hơn bằng metrics upstream thay vì ép gán trace xuyên service khi không có trace_id trùng.

## Notes

- Một số log timeout ở `order-service` có thể xuất hiện sớm trong ngày như noise nền, nên không dùng một timeout đơn lẻ làm root cause chính.
- Root cause được chọn dựa trên chuỗi tín hiệu nhất quán giữa memory, GC, timeout, và OOM.
