# SUBMIT — ShopX Incident Lab

## Tóm tắt

Bài lab này phân tích incident của `cart-service` dựa trên metrics và logs trong 24 giờ telemetry cuối trước khi sự cố được suppress.

## Deliverables

- [`scripts/run_pipeline.py`](./scripts/run_pipeline.py)
- [`FINDINGS.md`](./FINDINGS.md)
- [`SUBMIT.md`](./SUBMIT.md)

## Khi nào anomaly bắt đầu

- Tín hiệu log sớm xuất hiện từ khoảng `2026-06-01 16:00:01Z`
- Tín hiệu metric bền vững hơn từ khoảng `2026-06-01 16:20:30Z`
- GC anomaly rõ hơn từ khoảng `2026-06-01 17:24:30Z`
- Hard failure vào khoảng `2026-06-01 19:59:00Z`

## Service / metric / log nổi bật

- `cart-service` là nguồn gốc chính
- `jvm_gc_pause_ms_avg` và `memory_usage_bytes` là hai metric dẫn đầu
- `ProductCatalogCache eviction failed: heap pressure too high` là log signal sớm nhất
- `OutOfMemoryError imminent` và `Container OOMKilled` xác nhận cơ chế sập

## Bảng mapping WHEN / WHERE / WHAT

| File | WHEN | WHERE | WHAT |
|---|---|---|---|
| `metrics/cart-service.csv` | Rất quan trọng | Rất quan trọng | Rất quan trọng |
| `logs/cart-service.log.jsonl` | Quan trọng | Rất quan trọng | Rất quan trọng |
| `metrics/api-gateway.csv` | Quan trọng | Hỗ trợ | Hỗ trợ |
| `metrics/order-service.csv` | Quan trọng | Hỗ trợ | Hỗ trợ |
| `metrics/payment-service.csv` | Quan trọng | Hỗ trợ | Hỗ trợ |
| `logs/order-service.log.jsonl` | Hỗ trợ | Quan trọng | Hỗ trợ |
| `metrics/product-service.csv` | Đối chứng | Đối chứng | Đối chứng |

## Root cause

Hypothesis chính:

- cache / heap pressure tăng dần trong `cart-service`
- GC tăng mạnh
- latency tăng
- pod bị `OOMKilled`
- restart loop gây timeout lan sang `api-gateway`, `order-service`, và `payment-service`

## Reflection

Nếu làm lại bài này cho nhóm 50-service, mình sẽ:

- bắt đầu từ `cart-service` vì đây là root subsystem
- luôn dùng 2 lớp bằng chứng: metric anomaly và log template
- ưu tiên timestamp cụ thể thay vì mô tả chung chung
- dùng trace_id để correlate logs trong cùng service, nhưng không giả định trace xuyên service nếu data không cung cấp

## Cách chạy

```bash
python scripts/run_pipeline.py
```
