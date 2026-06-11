# SUBMIT



## Những gì đã hoàn thành

- Xác nhận `models/anomaly-detector.py` chạy được và tạo model `anomaly-detector.pkl`
- Xác nhận `models/rca-engine.py` chạy đúng cho scenario `S06`
- Xác nhận `models/log-clusterer.py` train được từ dữ liệu log
- Chạy kiểm chứng đầy đủ 3 notebook `ex01`, `ex02`, `ex03`
- Tạo báo cáo `FINDINGS.md`
- Lưu ảnh minh chứng vào `submission/screenshots/`

## Cách kiểm tra lại

```bash
python models/anomaly-detector.py --train --scenario S01 --service esb --metric latency_p99_ms
python models/rca-engine.py --scenario S06
python models/log-clusterer.py --show 5
```

