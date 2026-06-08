# Detection Approach — DESIGN.md

## Approach tôi dùng
Hệ thống sử dụng tiếp cận nhiều lớp (Multi-layered approach):
- **Rolling Z-score**: Để đo độ lệch của metrics so với baseline động.
- **Rule-based trend detection**: Để kiểm tra xu hướng tăng liên tục và các điều kiện ngữ cảnh của từng loại lỗi.
- **M-out-of-N filtering**: Bộ lọc nhiễu thời gian thực trước khi bắn cảnh báo.
- **Alert suppression**: Cơ chế chống alert storm (suppress trong 60 giây).

## Tại sao chọn approach này
- **Thích hợp cho streaming data**: Phù hợp chạy online theo từng điểm dữ liệu, hiệu năng cao và độ trễ thấp.
- **Dễ giải thích & trực quan**: Không cần huấn luyện mô hình học máy phức tạp, dễ dàng kiểm chứng bằng luật logic (rules) trên các thuộc tính vận hành (SRE metrics).
- **Độ tin cậy cao**: Sự kết hợp giữa Z-score (độ lệch thống kê) và các luật ngữ cảnh cụ thể cho từng loại sự cố (`memory_leak`, `traffic_spike`, `dependency_timeout`) giúp phân loại chính xác lỗi.

## Cách hoạt động
1. **Thu thập và Tiền xử lý (FastAPI Endpoint `/ingest`)**: Nhận telemetry payload chứa metrics và logs từ generator, tính toán các metrics phái sinh (ví dụ: `memory_utilization`).
2. **Cập nhật Rolling Stats**: Đẩy metrics mới vào hàng đợi rolling window để cập nhật giá trị trung bình (`mean`) và độ lệch chuẩn (`std`).
3. **Phát hiện Anomaly theo Fault Type**:
   - Sử dụng các luật kiểm tra kết hợp ngưỡng cứng, Rolling Z-score, và hướng xu hướng (`trend_up`) cho từng fault type cụ thể để tính điểm bất thường.
4. **Chọn Fault Type tối ưu**: Phân loại và chấm điểm cho cả 3 ứng viên, chọn loại fault có điểm cao nhất.
5. **M-out-of-N Filtering**: Đưa cờ hiệu bất thường của fault type chiến thắng qua bộ lọc M-out-of-N (nếu có ít nhất M điểm bất thường trong N quan sát gần nhất thì xác nhận sự cố thực sự).
6. **Suppression & Alerting**: Kiểm tra khoảng cách thời gian từ lần alert trước đó. Nếu không bị suppression, ghi alert dưới dạng một dòng JSON vào file `alerts.jsonl`.

## Parameters tôi chọn
- **`WINDOW_SIZE = 50`**: Độ dài rolling window vừa đủ để phản ánh baseline ngắn hạn đáng tin cậy (~25 phút sản xuất với tốc độ lấy mẫu chuẩn) mà không tiêu tốn quá nhiều bộ nhớ.
- **`WARMUP_POINTS = 20`**: Số điểm tối thiểu để khởi tạo baseline thống kê ổn định trước khi bắt đầu kiểm tra bất thường.
- **`M_OUT_OF_N = 3` / `M_OUT_OF_N_WINDOW = 5`**: Lọc nhiễu ngắn hạn hiệu quả (tránh false positive do 1-2 điểm nhiễu đơn lẻ) trong khi vẫn đảm bảo thời gian phát hiện lỗi (Time-To-Detect) đủ nhanh (chỉ cần tối đa 3-5 ticks).
- **`ALERT_SUPPRESSION_SECONDS = 60`**: Ngăn ngừa bão cảnh báo (alert storm) giúp nhân viên on-call không bị quá tải.

## Cải thiện nếu có thêm thời gian
- Áp dụng **EWMA (Exponentially Weighted Moving Average)** thay thế hoặc bổ trợ cho Rolling Z-score để bắt các tín hiệu drift mịn màng hơn.
- Thiết lập các ngưỡng Z-score động và cấu hình riêng cho từng metric thay vì sử dụng ngưỡng chung.
- Tích hợp thêm các kỹ thuật phân tích log nâng cao (như Parsing Drain3) để ánh xạ log template động vào điểm bằng chứng thay vì kiểm tra từ khóa tĩnh (`timeout`, `overloaded`).
