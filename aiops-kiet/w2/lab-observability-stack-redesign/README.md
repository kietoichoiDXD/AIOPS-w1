# README

## Cách chạy

Đây là bộ bài thiết kế lại observability stack cho GeekShop.

Các file chính:
- `FINDINGS.md` - phân tích kiến trúc, ADR, migration plan, risk register
- `architecture.mmd` - sơ đồ kiến trúc Mermaid

## Cách dùng Mermaid

Mở `architecture.mmd` bằng GitHub hoặc Mermaid Live Editor để render sơ đồ.

## Cách xuất ảnh đẹp bằng Graphviz

Nếu đã cài Graphviz, dùng các lệnh sau:

```bash
dot -Tpng architecture.dot -o architecture.png
dot -Tsvg architecture.dot -o architecture.svg
```

## Gợi ý vẽ đẹp hơn

Nếu muốn xuất ảnh:
- dùng `Mermaid` cho nhanh và dễ review
- dùng `Graphviz` nếu muốn layout chặt và xuất PNG/SVG đẹp hơn

## Ghi chú

Toàn bộ thiết kế bám theo yêu cầu:
- giảm chi phí ít nhất 40%
- giảm MTTR ít nhất 30%
- không đánh đổi mất incident-response
- có rollback path cho từng giai đoạn migration
