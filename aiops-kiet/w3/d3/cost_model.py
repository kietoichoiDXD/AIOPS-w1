#!/usr/bin/env python3
"""Mô hình chi phí điểm hòa vốn cho nền tảng AIOps (§8).

Cách sử dụng:
    python cost_model.py
"""

def is_worth_it(
    num_services: int,
    incidents_per_month: int,
    avg_incident_duration_hours: float,
    downtime_cost_per_hour: float,
    expected_mttr_reduction_pct: float = 0.4,
    aiops_monthly_cost: float = 15_000,
) -> dict:
    """
    Tính toán Tỷ suất hoàn vốn (ROI) và thời gian hoàn vốn của nền tảng AIOps.
    """
    monthly_downtime_hours = incidents_per_month * avg_incident_duration_hours
    
    # Giá trị mang lại mỗi tháng bằng cách giảm thời gian phục hồi (MTTR)
    monthly_value = (
        monthly_downtime_hours 
        * expected_mttr_reduction_pct 
        * downtime_cost_per_hour
    )
    
    roi = monthly_value / aiops_monthly_cost if aiops_monthly_cost > 0 else float("inf")
    payback_months = aiops_monthly_cost / monthly_value if monthly_value > 0 else float("inf")
    
    if roi > 1.5:
        verdict = "Đáng giá (worth_it)"
    elif roi > 1.0:
        verdict = "Cận biên (marginal)"
    else:
        verdict = "Không đáng (not_worth_it)"

    return {
        "Giá trị hàng tháng (monthly_value)": monthly_value,
        "Chi phí hàng tháng (monthly_cost)": aiops_monthly_cost,
        "Tỷ suất hoàn vốn (roi)": roi,
        "Thời gian hoàn vốn / tháng (payback_months)": payback_months,
        "Kết luận (verdict)": verdict
    }

if __name__ == "__main__":
    print("--- Ví dụ 1 ---")
    res1 = is_worth_it(num_services=20, incidents_per_month=2, avg_incident_duration_hours=1, downtime_cost_per_hour=10_000, aiops_monthly_cost=15_000)
    for k, v in res1.items():
        print(f"{k}: {v}")
    
    print("\n--- Ví dụ 2 ---")
    res2 = is_worth_it(num_services=100, incidents_per_month=5, avg_incident_duration_hours=2, downtime_cost_per_hour=20_000, aiops_monthly_cost=25_000)
    for k, v in res2.items():
        print(f"{k}: {v}")

    print("\n--- Ví dụ 3 (Kịch bản công ty lớn) ---")
    # Kịch bản: Sàn Thương mại điện tử lớn (như Amazon). Chi phí downtime cực cao ($200k/giờ).
    # Chỉ cần một sự giảm nhẹ trong MTTR cũng mang lại giá trị cực lớn.
    res3 = is_worth_it(
        num_services=500, 
        incidents_per_month=10, 
        avg_incident_duration_hours=1.5, 
        downtime_cost_per_hour=200_000,  # $200k/giờ cho TMĐT lớn
        expected_mttr_reduction_pct=0.4,
        aiops_monthly_cost=60_000
    )
    for k, v in res3.items():
        print(f"{k}: {v}")
