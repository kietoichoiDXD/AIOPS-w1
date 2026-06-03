# Bài nộp W1-D3

## Tóm tắt

Bài này hoàn thiện một kiến trúc AIOps cho use case `anomaly detection trên payment service`, gồm 4 phần:

- `pipeline.py`: mô phỏng streaming pipeline đọc dữ liệu NAB và tạo feature theo kiểu streaming
- `architecture.md` và `architecture.png`: mô tả kiến trúc dữ liệu đầu-cuối
- `cost_model.py`: ước tính chi phí cho 3 quy mô
- `ADR-001.md`: ghi lại quyết định kiến trúc quan trọng

## 1. Sơ đồ kiến trúc

Sơ đồ kiến trúc nằm ở:

- [`architecture.md`](./architecture.md)
- [`architecture.png`](./architecture.png)

Use case được chọn:

- Anomaly detection trên `payment service`

Chuỗi thành phần:

- Service
- Collection
- Transport
- Processing
- Storage
- Query / ML

## 2. Pipeline mô phỏng streaming

`pipeline.py` đọc dữ liệu từ source NAB:

- `data/raw/machine_temperature_system_failure.csv`
- link tham chiếu: `https://raw.githubusercontent.com/numenta/NAB/master/data/realKnownCause/machine_temperature_system_failure.csv`

Luồng xử lý:

1. Producer giả lập đọc từng dòng CSV.
2. Producer đẩy từng event vào `queue.Queue` như fake Kafka producer.
3. Consumer đọc stream từ queue.
4. Consumer tính các feature:
   - rolling mean 1 giờ
   - rolling std 1 giờ
   - rolling mean 24 giờ
   - rate of change
   - rate of change 1 giờ
5. Kết quả được ghi ra:
   - `features.parquet` nếu môi trường có hỗ trợ
   - hoặc `features.json` nếu không có Parquet backend

Lệnh chạy:

```bash
uv run python pipeline.py
```

Kết quả kiểm tra thực tế:

- Input rows: `22695`
- Output rows: `22695`
- File output: `features.json`

## 3. Ước tính chi phí

`cost_model.py` ước tính chi phí theo 3 tier:

- Small: 10 services, 50 GB log/day, 100K events/sec metric
- Medium: 100 services, 500 GB log/day, 1M events/sec metric
- Large: 1000 services, 5 TB log/day, 10M events/sec metric

Script in ra bảng cost breakdown cho:

- storage
- compute
- network
- total

và so sánh:

- Build
- Datadog SaaS

Lệnh chạy:

```bash
uv run python cost_model.py
```

## 4. ADR

File [`ADR-001.md`](./ADR-001.md) ghi lại quyết định:

- Chọn Kafka làm lớp transport cho telemetry

Điểm chính:

- giảm phụ thuộc trực tiếp giữa producer và storage
- hỗ trợ replay khi downstream lỗi
- chịu burst tốt hơn
- cho phép nhiều consumer đọc cùng một stream

Trade-off:

- tăng độ phức tạp vận hành
- tăng latency nhẹ so với direct push

## 5. Reflection

Nếu mình được hire làm Platform Engineer cho startup 50-service vừa raise Series A, mình sẽ recommend:

- build phần lõi cần kiểm soát chặt như pipeline stream, feature processing, và logic nội bộ quan trọng
- buy các phần rất tốn công vận hành như observability SaaS hoặc managed storage ở giai đoạn đầu

Vì sao:

- team quy mô này cần đi nhanh
- chưa nên tự xây toàn bộ platform từ đầu
- nhưng cũng không nên phụ thuộc hoàn toàn vào vendor nếu chi phí tăng mạnh khi scale

Kết luận:

- chiến lược hợp lý nhất là `build-first có chọn lọc` và `buy` những phần có chi phí vận hành cao

## 6. Kết quả đã tạo

Các file trong `w1/d3/`:

- [`pipeline.py`](./pipeline.py)
- [`architecture.md`](./architecture.md)
- [`architecture.png`](./architecture.png)
- [`cost_model.py`](./cost_model.py)
- [`ADR-001.md`](./ADR-001.md)
- [`features.json`](./features.json)

## 7. Ghi chú

File này được viết bằng tiếng Việt và lưu UTF-8.
