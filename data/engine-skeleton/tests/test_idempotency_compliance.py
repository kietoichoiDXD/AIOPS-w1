import pytest
import copy

def test_detect_idempotency(client, valid_headers, detect_payload):
    h = copy.deepcopy(valid_headers)
    h["X-Dry-Run-Mode"] = "false"
    key = "tenant-001:2026-06-30:daily-batch"
    h["X-Idempotency-Key"] = key

    # First request
    resp1 = client.post("/v1/detect", json=detect_payload, headers=h)
    assert resp1.status_code == 200
    res1_body = resp1.json()

    # Second request - same payload (cache hit)
    resp2 = client.post("/v1/detect", json=detect_payload, headers=h)
    assert resp2.status_code == 200
    assert resp2.json() == res1_body

    # Third request - different payload (mismatch)
    diff_payload = copy.deepcopy(detect_payload)
    if "aws_cost_explorer_daily" in diff_payload and len(diff_payload["aws_cost_explorer_daily"]) > 0:
        diff_payload["aws_cost_explorer_daily"][0]["cost_ratio_to_7d_avg"] = 99.9
    else:
        diff_payload["is_ad_hoc"] = False
        # Fallback payload modification if CE is missing
        diff_payload["aws_cur_line_items"] = []
    resp3 = client.post("/v1/detect", json=diff_payload, headers=h)
    assert resp3.status_code == 400
    assert resp3.json()["error_code"] == "ERR_IDEMPOTENCY_MISMATCH"


def test_decide_idempotency(client, valid_headers, decide_payload):
    h = copy.deepcopy(valid_headers)
    h["X-Dry-Run-Mode"] = "false"
    key = "tenant-001:2026-06-30:decide"
    h["X-Idempotency-Key"] = key

    # First request
    resp1 = client.post("/v1/decide", json=decide_payload, headers=h)
    assert resp1.status_code == 200
    res1_body = resp1.json()

    # Second request - same payload (cache hit)
    resp2 = client.post("/v1/decide", json=decide_payload, headers=h)
    assert resp2.status_code == 200
    assert resp2.json() == res1_body

    # Third request - different payload (mismatch)
    diff_payload = copy.deepcopy(decide_payload)
    diff_payload["dry_run_mode"] = False if decide_payload["dry_run_mode"] else True
    resp3 = client.post("/v1/decide", json=diff_payload, headers=h)
    assert resp3.status_code == 400
    assert resp3.json()["error_code"] == "ERR_IDEMPOTENCY_MISMATCH"


def test_verify_idempotency(client, valid_headers, verify_payload):
    h = copy.deepcopy(valid_headers)
    h["X-Dry-Run-Mode"] = "false"
    key = "tenant-001:2026-06-30:verify"
    h["X-Idempotency-Key"] = key

    # First request
    resp1 = client.post("/v1/verify", json=verify_payload, headers=h)
    assert resp1.status_code == 200
    res1_body = resp1.json()

    # Second request - same payload (cache hit)
    resp2 = client.post("/v1/verify", json=verify_payload, headers=h)
    assert resp2.status_code == 200
    assert resp2.json() == res1_body

    # Third request - different payload (mismatch)
    diff_payload = copy.deepcopy(verify_payload)
    diff_payload["dry_run_mode"] = False if verify_payload["dry_run_mode"] else True
    resp3 = client.post("/v1/verify", json=diff_payload, headers=h)
    assert resp3.status_code == 400
    assert resp3.json()["error_code"] == "ERR_IDEMPOTENCY_MISMATCH"
