# DESIGN - Streaming Anomaly Pipeline

## 1. Kiến trúc

Hệ thống gồm 3 phần:

1. `stream_generator.py` gửi telemetry liên tục qua HTTP `POST /ingest`.
2. `pipeline.py` nhận payload, cập nhật rolling window và tính điểm bất thường.
3. `alerts.jsonl` lưu alert khi pipeline xác nhận có anomaly.

Ngoài ra, `pipeline.log` ghi lại số request, anomaly và alert để thuận tiện khi demo.

## 2. Cách phát hiện bất thường

Pipeline dùng cách tiếp cận nhiều lớp:

- `Rolling Z-score` để đo độ lệch so với baseline.
- `Rule-based trend detection` để kiểm tra xu hướng tăng liên tục.
- `M-out-of-N filtering` để tránh báo động chỉ vì một vài điểm nhiễu.
- `Alert suppression` 60 giây để chống alert storm.

Đầu ra được phân loại theo ba fault type:

- `memory_leak`
- `traffic_spike`
- `dependency_timeout`

## 3. Vì sao dùng Rolling Z-score

Rolling Z-score phù hợp cho bài streaming vì:

- dễ giải thích trong buổi demo
- không cần train mô hình phức tạp
- chạy online theo từng điểm dữ liệu
- phát hiện được độ lệch bất thường của memory, latency, timeout, queue depth

Trong bài này, Z-score không đứng một mình mà đi kèm xu hướng tăng và điều kiện theo ngữ cảnh.

## 4. Vì sao dùng M-out-of-N

Streaming telemetry thường có nhiễu ngắn hạn. Nếu bắn alert ngay ở một điểm, hệ thống rất dễ false positive.

M-out-of-N giúp lọc nhiễu bằng cách chỉ fire alert khi có ít nhất `3` anomaly trong `5` quan sát gần nhất.

Lợi ích:

- giảm alert giả
- tránh alert storm
- vẫn giữ được khả năng phát hiện sớm

## 5. Chiến lược phân loại fault

Pipeline không dùng một detector chung cho mọi fault. Thay vào đó, mỗi fault type có tiêu chí riêng:

- `memory_leak`
  - memory utilization tăng
  - GC pause tăng
  - latency tăng

- `traffic_spike`
  - request rate tăng
  - queue depth tăng
  - latency tăng

- `dependency_timeout`
  - timeout rate tăng
  - latency tăng
  - 5xx tăng
  - log có `timeout` hoặc `circuit breaker`

Sau đó pipeline chọn fault type có điểm cao nhất.

## 6. Giới hạn

- Rolling Z-score cần baseline ban đầu đủ ổn định.
- Nếu fault thay đổi quá đột ngột, window ngắn có thể bỏ sót một số tín hiệu.
- Rule-based logic dễ giải thích nhưng không linh hoạt bằng model học máy.
- M-out-of-N có thể làm chậm phát hiện một chút để đổi lấy độ tin cậy cao hơn.

## 7. Cải tiến tương lai

- Thêm EWMA cho drift mịn.
- Tách ngưỡng riêng cho từng fault type.
- Lưu thêm correlation id hoặc trace id vào alert.
- Tạo dashboard nhỏ hiển thị trend trước khi alert.
- Thêm unit test cho từng detector và từng loại fault.
