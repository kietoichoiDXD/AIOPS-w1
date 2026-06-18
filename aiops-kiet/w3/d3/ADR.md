# ADR-007: Sử dụng phân tích nguyên nhân gốc rễ (RCA) dựa trên Topology thay vì xếp hạng theo số lượng

> Định dạng: Nygard (2011)

## Trạng thái
Được chấp thuận (Accepted)

## Bối cảnh (Context)
Khi có sự cố xảy ra, nền tảng AIOps của chúng ta nhận được hàng trăm cảnh báo. Công cụ Phân tích nguyên nhân gốc rễ (RCA) cần phải chọn ra dịch vụ gốc gây ra lỗi từ N dịch vụ đang phát ra cảnh báo. Nếu sử dụng cách xếp hạng đếm số lượng cảnh báo thông thường (dịch vụ có nhiều cảnh báo nhất là nguyên nhân gốc), nó sẽ thất bại hoàn toàn trong các sự cố dây chuyền (cascading failures). Ví dụ, một dịch vụ bị lỗi ở phía hạ nguồn (downstream) và liên tục gửi lại yêu cầu (retry storm) sẽ phát ra nhiều cảnh báo hơn rất nhiều so với dịch vụ ở thượng nguồn (upstream) thực sự gây ra lỗi.

## Quyết định (Decision)
Chúng ta sẽ kết hợp 3 tín hiệu cho engine RCA:
1. Khoảng cách cấu trúc mạng (Topology distance) từ điểm truy cập (ưu tiên upstream)
2. Thời gian lệch chuẩn đầu tiên (Phân tích độ trễ nhân quả thông qua Granger causality)
3. Số lượng cảnh báo (Chỉ dùng để phá vỡ thế hòa khi các tín hiệu trên bằng nhau)

## Các giải pháp thay thế đã xem xét
1. **Chỉ xếp hạng theo số lượng** — đơn giản và nhanh, nhưng hoàn toàn thất bại trong bão retry và lỗi dây chuyền. Bị từ chối.
2. **RCA chỉ dùng LLM** — rất linh hoạt, nhưng dễ bịa ra (hallucinate) một nguyên nhân sai một cách tự tin và quá chậm để xử lý theo thời gian thực. Bị từ chối làm phương pháp chính.
3. **Chỉ dùng thuật toán Graph PageRank** — phản ánh tốt cấu trúc Topology nhưng bỏ qua tính nhân quả thời gian (dịch vụ nào suy thoái trước). Bị từ chối làm giải pháp độc lập.

## Hậu quả (Consequences)
- **Tích cực:** Nắm bắt được các mẫu lỗi dây chuyền mà các thuật toán đếm số lượng bỏ sót (đã được xác minh qua các kịch bản mô phỏng Roblox và AWS S3).
- **Tích cực:** Kiến trúc thành phần (Composable) nghĩa là mỗi tín hiệu sẽ tự động giảm chất lượng một cách an toàn nếu dữ liệu bị thiếu.
- **Tiêu cực:** Chi phí điện toán (compute) cao hơn, đặc biệt là khi tính toán Granger causality (O(n × lag_window)).
- **Rủi ro mới phát sinh:** Đòi hỏi biểu đồ phụ thuộc dịch vụ (Topology graph) phải được cập nhật nghiêm ngặt, gây thêm gánh nặng cho vận hành. Nếu biểu đồ bị cũ (stale), RCA sẽ chỉ nhầm vào dịch vụ upstream khác.
- **Những thứ bị khóa (Locked in):** Từ nay chúng ta bị phụ thuộc vào một hệ thống biểu đồ phụ thuộc dịch vụ liên tục được cập nhật.
