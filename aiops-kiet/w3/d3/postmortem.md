# Báo cáo sự cố (Postmortem): Sự cố AWS S3 US-EAST-1 (2017-02-28)

## Tóm tắt
Vào ngày 28 tháng 2 năm 2017, dịch vụ Amazon S3 tại khu vực US-EAST-1 đã gặp sự cố gián đoạn nghiêm trọng kéo dài khoảng 4 giờ. Một công cụ vận hành đã được thực thi với dữ liệu đầu vào không chính xác trong một phiên gỡ lỗi định kỳ, vô tình xóa bỏ dung lượng (capacity) quan trọng của các hệ thống con S3 Index và Placement. Điều này gây ra lỗi hàng loạt cho các yêu cầu `GET`, `LIST`, `PUT`, và `DELETE`, đồng thời lan rộng sang các dịch vụ AWS khác phụ thuộc vào S3.

## Mức độ ảnh hưởng
- **Người dùng bị ảnh hưởng:** Gần như tất cả khách hàng sử dụng S3 và các dịch vụ AWS phụ thuộc tại khu vực US-EAST-1.
- **Dịch vụ bị ảnh hưởng:** S3, EC2, EBS, Lambda, AWS Service Health Dashboard, và nhiều dịch vụ khác.
- **Ảnh hưởng Doanh thu/SLA:** Nghiêm trọng, dẫn đến việc phải bồi thường SLA cho khách hàng bị ảnh hưởng.
- **Thời gian:** 17:37 UTC đến 21:40 UTC (4 giờ, 3 phút)

## Dòng thời gian (UTC)

| UTC | Sự kiện |
|-----|-------|
| 2017-02-28 17:35 | Một thành viên được ủy quyền của đội ngũ S3 bắt đầu gỡ lỗi gây chậm hệ thống thanh toán S3 (billing). |
| 2017-02-28 17:37 | Người vận hành chạy một lệnh nhằm gỡ bỏ một số lượng nhỏ các máy chủ thuộc hệ thống thanh toán. |
| 2017-02-28 17:38 | Do tham số đầu vào bị sai, lệnh này đã gỡ bỏ một tập hợp máy chủ khổng lồ, bao gồm cả hai hệ thống con cực kỳ quan trọng là Index và Placement. |
| 2017-02-28 17:40 | Triệu chứng ban đầu xuất hiện: Tỷ lệ lỗi API S3 tăng vọt và độ sẵn sàng giảm mạnh tại US-EAST-1. |
| 2017-02-28 17:45 | Hệ thống cảnh báo tự động (burn-rate alerts) được kích hoạt và gọi kỹ sư trực ca (on-call). |
| 2017-02-28 17:55 | Đội phản ứng sự cố xác định được nguyên nhân gốc rễ là do thiếu dung lượng của Index và Placement và ngay lập tức dừng mọi thay đổi khác. |
| 2017-02-28 18:15 | Các kỹ sư bắt đầu quá trình khởi động lại cực kỳ phức tạp cho hệ thống Index và Placement, quá trình này đòi hỏi phải xây dựng lại toàn bộ trạng thái (state). |
| 2017-02-28 21:00 | Hệ thống Index hoàn tất quá trình khởi động lại và hoạt động đầy đủ. |
| 2017-02-28 21:40 | Hệ thống Placement hoàn tất quá trình khôi phục. S3 US-EAST-1 khôi phục hoàn toàn và tỷ lệ lỗi trở lại bình thường. |

## Nguyên nhân gốc rễ (Root cause)
Công cụ vận hành được sử dụng để gỡ bỏ máy chủ thiếu các rào chắn bảo vệ (guardrails), cho phép một lệnh với tham số đầu vào sai giảm mạnh dung lượng của các hệ thống con quan trọng xuống dưới mức tối thiểu cần thiết để hoạt động.

## Các yếu tố góp phần gây sự cố (Contributing factors)
1. **Thiếu giới hạn dung lượng tối thiểu:** Công cụ vận hành không có kiểm tra để ngăn chặn việc gỡ bỏ máy chủ xuống dưới mức tối thiểu cần thiết cho các hệ thống con hoạt động.
2. **Thời gian phục hồi chậm:** Hệ thống Index và Placement cần một thời gian khởi động lại rất lâu để xây dựng lại trạng thái siêu dữ liệu (metadata state), kéo dài thời gian mất mạng đáng kể.
3. **Phạm vi ảnh hưởng (Blast radius) quá rộng:** Công cụ này đã xóa bỏ máy chủ đồng loạt trên toàn bộ khu vực thay vì làm một cách từ từ.

## Phát hiện sự cố (Detection)
- **Được phát hiện như thế nào?** Thông qua các cảnh báo nội bộ (SLO burn-rate) và các báo cáo tức thời từ khách hàng.
- **MTTD (Mean Time To Detect):** ~3 phút (từ nguyên nhân lúc 17:37 đến khi có cảnh báo/triệu chứng lúc 17:40).
- **Khoảng trống của Pipeline phát hiện được trong quá trình mô phỏng:**
  - Khoảng trống 1: Pipeline AIOps ban đầu gặp khó khăn trong việc chỉ ra nguyên nhân gốc rễ giữa hàng trăm cảnh báo dây chuyền từ các dịch vụ bị ảnh hưởng.
  - Khoảng trống 2: Pipeline không liên kết trực tiếp sự kiện thực thi lệnh của người vận hành/triển khai với việc giảm sút đột ngột của các chỉ số (metrics).

## Phản hồi sự cố (Response)
- **Hành động của người phản hồi đầu tiên:** Các kỹ sư trực ca đã dừng mọi tác vụ vận hành và bắt đầu điều tra sự cố mất máy chủ đột ngột.
- **Thời gian giảm thiểu (Time to mitigate):** Nguyên nhân gốc rễ được phát hiện và ngăn chặn trong vòng 18 phút, nhưng để khôi phục hoàn toàn cần phải khởi động lại các hệ thống.
- **Thời gian giải quyết hoàn toàn (Time to fully resolve):** 4 giờ và 3 phút.

## Kế hoạch hành động (Action items)
| # | Hành động | Người phụ trách | Loại | Thời hạn (ETA) |
|---|--------|-------|------|-----|
| 1 | Thêm các rào chắn giới hạn dung lượng tối thiểu vào công cụ vận hành để ngăn chặn việc xóa bỏ máy chủ dưới ngưỡng an toàn. | Đội Công cụ (Tools Team) | Phòng ngừa | 2017-03-05 |
| 2 | Sửa đổi công cụ gỡ bỏ máy chủ để bắt buộc việc gỡ bỏ phải diễn ra chậm và từ từ, nhằm hạn chế phạm vi ảnh hưởng của bất kỳ lỗi nào trong tương lai. | Đội Công cụ (Tools Team) | Giảm thiểu | 2017-03-10 |
| 3 | Kiểm toán tất cả các công cụ vận hành khác trên toàn AWS để tìm kiếm các giới hạn an toàn bị thiếu tương tự và bổ sung các rào chắn. | Đội SRE | Phòng ngừa | 2017-03-30 |
| 4 | Tách rời Dashboard Sức khỏe Dịch vụ AWS (Service Health Dashboard) khỏi sự phụ thuộc vào S3 của một khu vực duy nhất để đảm bảo nó vẫn khả dụng trong thời gian mất mạng. | Đội Web (Web Team) | Giảm thiểu | 2017-03-15 |
