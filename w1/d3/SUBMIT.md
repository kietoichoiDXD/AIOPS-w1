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

### Giải thích mô hình chi phí

Mô hình này được viết để dễ bảo vệ khi trình bày, nên mình tách chi phí thành 3 nhóm chính:

- `storage`: gồm log hot/cold tier và metric retention
- `compute`: gồm collector, Kafka, và stream processing
- `network`: gồm chi phí truyền dữ liệu telemetry mỗi tháng

Giả định chính:

- log được chia thành `20% hot` và `80% cold`
- metrics được quy đổi theo số sample mỗi tháng
- build-first sẽ có thêm chi phí vận hành hạ tầng như Kafka và stream processor

Ý nghĩa của bảng:

- `Build` phù hợp khi muốn kiểm soát dữ liệu và chi phí theo scale
- `Datadog` phù hợp khi ưu tiên tốc độ triển khai và giảm gánh vận hành
- ở quy mô càng lớn, phần cost chênh lệch cần được cân nhắc cùng với effort vận hành và yêu cầu compliance

### Bảng cost estimate

| Tier | Option | Storage | Compute | Network | Total |
|---|---|---:|---:|---:|---:|
| Small | Build | 1307.76 | 398.00 | 697.08 | 2402.84 |
| Small | Datadog | 645.00 | 275.00 | 1053.12 | 1973.12 |
| Medium | Build | 13077.60 | 3005.00 | 6970.80 | 23053.40 |
| Medium | Datadog | 6450.00 | 2750.00 | 10531.20 | 19731.20 |
| Large | Build | 130776.00 | 30050.00 | 69708.00 | 230534.00 |
| Large | Datadog | 64500.00 | 27500.00 | 105312.00 | 197312.00 |

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
