# W3-D3 Bài nộp (Submission)

## Sự cố được chọn
- ID: 1
- Tên sự cố: AWS S3 2017-02-28
- Lý do chọn: Tôi cực kỳ quan tâm đến cách một lỗi gõ nhầm của người vận hành có thể đánh sập một phần lớn của mạng internet. Nó làm nổi bật tầm quan trọng tối thượng của các rào chắn bảo vệ (guardrails) trong các công cụ vận hành, chứ không chỉ ở mã nguồn.
- Mô hình lỗi (Failure mode): Hành động của người vận hành mà không có rào chắn an toàn (Operator action without guardrail)

## 3 điều tôi học được từ sự cố này
1. **Lỗi con người là hệ quả của lỗ hổng hệ thống:** Đừng trách người gõ nhầm lệnh. Hãy trách công cụ đã cho phép một lệnh gõ nhầm phá hủy toàn bộ hệ thống. Triết lý "Không đổ lỗi" (Blameless) là phải đi tìm lỗ hổng này.
2. **Phạm vi ảnh hưởng (Blast radius) quá rộng:** Công cụ quản trị không có giới hạn an toàn (minimum capacity constraints) và không thực hiện gỡ bỏ dần dần, dẫn đến việc xóa hàng loạt server cùng lúc.
3. **Restart không bao giờ là tức thời:** Việc khởi động lại hệ thống phân tán phức tạp như S3 Index cần một thời gian rất dài để khởi tạo lại state/metadata, khiến downtime bị kéo dài lên đến 4 tiếng.

## 1 thứ pipeline của tôi sẽ vẫn bỏ lỡ nếu sự cố này xảy ra thực tế
- Mô hình (Pattern): Hành động của Operator / Cập nhật cấu hình (Config push).
- Tại sao bị lỡ: Pipeline AIOps hiện tại chỉ phân tích metric và log từ các service, nhưng không đọc các sự kiện thay đổi cấu hình (config changes) hoặc lệnh thực thi từ CLI của operator. Khi metric sập, pipeline chỉ biết là sập, không biết do ai gõ lệnh gì.
- Ý tưởng khắc phục (Mitigation idea): Đưa các sự kiện Audit Log (lệnh CLI, Git push, config change) vào làm một nguồn dữ liệu sự kiện (deployment events) để Correlator liên kết với sự thay đổi của metric.

## 1 quyết định trong ADR mà tôi không hoàn toàn chắc chắn
Quyết định dùng thuật toán Nhân quả Granger (Granger Causality) để tìm độ trễ đầu tiên (first-drift time) cho RCA. Việc tính toán ma trận quan hệ nhân quả cho hàng ngàn chuỗi thời gian (time series) khi có sự cố là cực kỳ tốn kém về mặt tính toán (compute). Tôi lo ngại trong lúc sự cố đang cao trào, hệ thống AIOps sẽ bị nghẽn (CPU pegged) do xử lý toán học nặng, dẫn đến chậm trễ báo cáo.

## Đánh giá mô hình chi phí cho Stack của tôi (Sàn TMĐT lớn)
- Tỷ suất hoàn vốn (ROI): 20.0
- Thời gian hoàn vốn: ~0.05 tháng (Chưa đến 2 ngày)
- Kết luận (Verdict): Cực kỳ đáng giá (worth_it) - Vì chi phí downtime lên đến $200k/giờ, nền tảng AIOps mang lại giá trị tiết kiệm cực kỳ khổng lồ.
