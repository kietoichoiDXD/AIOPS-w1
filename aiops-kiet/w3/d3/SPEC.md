# SPEC: Nền tảng AIOps XBrain

## 1. Tổng quan nền tảng
Nền tảng AIOps XBrain cung cấp tính năng phát hiện bất thường tự động, liên kết cảnh báo và phân tích nguyên nhân gốc rễ cho các microservices thương mại điện tử cốt lõi của chúng ta. Nền tảng này theo dõi các metrics, logs và traces để giảm thiểu đáng kể MTTR (Thời gian phục hồi trung bình) trong các sự cố Production. Nó tập trung hoàn toàn vào các dịch vụ backend (API gateway, payment, inventory, user services) và loại bỏ hoàn toàn các thông số từ phía client (frontend) khỏi phạm vi của nó.

## 2. Định nghĩa SLO (từ W3-D1)
- Mục tiêu SLO: 99.9%
- Chỉ báo mức độ dịch vụ (SLI): `count(2xx,3xx,4xx_not_429 AND latency < 200ms) / count(all)`
- Ngân sách lỗi (Error budget): 43 phút downtime mỗi tháng.
- Các mức cảnh báo tốc độ đốt ngân sách (Burn-rate alert tiers):
  - Tier 1: Cửa sổ 1h / 5 phút, tốc độ đốt >= 14.4 (Gọi On-Call ngay lập tức)
  - Tier 2: Cửa sổ 6h / 30 phút, tốc độ đốt >= 6 (Gọi On-Call)
  - Tier 3: Cửa sổ 3 ngày / 6 giờ, tốc độ đốt >= 1 (Tạo Ticket, xử lý trong giờ làm việc)

## 3. Ngăn xếp Phát hiện + Tương quan + RCA (từ W1+W2)
- **Trình phát hiện (Detector):** Thuật toán Isolation Forest + Ngưỡng 3-Sigma, lấy dữ liệu từ Prometheus TSDB, đầu ra là các sự kiện bất thường dạng JSON.
- **Trình liên kết (Correlator):** Thuật toán phân cụm DBSCAN gom các sự kiện theo thời gian trong một cửa sổ trượt 5 phút, đầu ra là các cụm sự cố.
- **RCA:** Thuật toán chấm điểm Nhân quả Granger kết hợp nhận diện cấu trúc mạng Topology, sử dụng biểu đồ phụ thuộc dịch vụ của Jaeger, đầu ra là danh sách xếp hạng các dịch vụ có khả năng là nguyên nhân gốc rễ nhất.

## 4. Xác minh độ tin cậy (từ W3-D2)
- Tần suất chạy thử nghiệm Hỗn loạn (Chaos run): Hàng tuần (10:00 sáng Thứ Ba theo giờ UTC)
- Tỷ lệ phát hiện / tổng sự cố mục tiêu: Độ chính xác (precision) > 90%, Độ thu hồi (recall) > 85%
- Tín hiệu trạng thái ổn định (Steady-state signal): Cả đầu dò mô phỏng (synthetic black-box probes) lẫn số liệu SLI nội bộ.

## 5. Mô hình vận hành (từ W3-D3)
- Template Báo cáo sự cố (Postmortem template): Theo định dạng Không đổ lỗi của Google SRE (postmortem.md)
- Luân phiên trực ca (On-call rotation): Theo mức độ cảnh báo với mô hình Bám theo mặt trời (Follow-The-Sun).
- Kho chứa quyết định kiến trúc (ADR repository): Thư mục ADR lưu trên Git, được rà soát mỗi 2 tuần.

## 6. Mô hình chi phí (từ W3-D3)
- Chi phí hàng tháng: $60,000 USD
- Số lượng sự cố cần tránh để hòa vốn: Thậm chí nếu chỉ giảm MTTR 40% trên tổng số 10 sự cố thì đã tiết kiệm được $1.2M USD/tháng cho công ty từ chi phí mất thời gian hoạt động, hoàn toàn xứng đáng với chi phí bỏ ra.
- Chi tiết xem file: `cost_model.py`

## 7. Những rủi ro chưa được giải quyết
- Rủi ro 1: Pipeline AIOps phụ thuộc vào biểu đồ phụ thuộc dịch vụ luôn phải được cập nhật mới nhất. Nếu biểu đồ cũ (stale), RCA sẽ chỉ ra sai dịch vụ. (Mức độ: Cao, Khắc phục: Tự động trích xuất cấu trúc mạng từ dấu vết của Jaeger hàng ngày).
- Rủi ro 2: Vòng lặp phụ thuộc giám sát (như sự cố của Roblox) nơi nền tảng AIOps dựa vào chính hệ thống hạ tầng mà nó đang giám sát. (Mức độ: Nghiêm trọng, Khắc phục: Lưu trữ nền tảng AIOps trên một cụm máy chủ vật lý hoàn toàn tách biệt).
