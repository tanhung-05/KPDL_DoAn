"""Parameter validation helpers for TA-PPHUIM demo pages."""

from __future__ import annotations


def validate_mining_parameters(stats: dict | None, params: dict) -> dict:
    """Validate Phase 1 mining parameters against temporal DB statistics."""
    warnings: list[str] = []
    errors: list[str] = []
    high_risk = False

    if not stats:
        errors.append("Chưa có temporal_db. Vui lòng chạy Preprocessing trước Phase 1.")
        return {"warnings": warnings, "errors": errors, "risk_level": "high"}

    num_transactions = _to_float(stats.get("num_transactions"))
    num_distinct_items = _to_float(stats.get("num_distinct_items"))
    avg_transaction_len = _to_float(stats.get("avg_transaction_len"))
    max_transaction_len = _to_float(stats.get("max_transaction_len"))

    mining_ratio = _to_float(params.get("mining_ratio"))
    sensitive_ratio = _to_float(params.get("sensitive_ratio"))
    candidate_mining_ratio = _to_float(params.get("candidate_mining_ratio"))
    max_patterns_per_window = _to_float(params.get("max_patterns_per_window"))

    if num_transactions > 5000:
        warnings.append("Dataset có hơn 5,000 transactions; live demo EFIM có thể chạy chậm.")
    if num_distinct_items > 1000:
        warnings.append("Dataset có hơn 1,000 item khác nhau; EFIM có thể tốn thời gian.")
    if avg_transaction_len > 30:
        warnings.append("Độ dài transaction trung bình lớn hơn 30; số tổ hợp item có thể tăng mạnh.")
    if candidate_mining_ratio < 0.005:
        high_risk = True
        warnings.append("Rủi ro cao: candidate_mining_ratio < 0.005 có thể sinh quá nhiều pattern.")
    if sensitive_ratio < mining_ratio:
        warnings.append(
            "sensitive_ratio thường nên >= mining_ratio trong demo này để chọn pattern nhạy cảm ổn định hơn."
        )
    if max_patterns_per_window > 10000:
        warnings.append("max_patterns_per_window > 10,000 có rủi ro tốn RAM khi hiển thị/lưu kết quả.")

    if max_transaction_len <= 0 and num_transactions > 0:
        warnings.append("Không đọc được max transaction length từ temporal_db.")

    if errors or high_risk:
        risk_level = "high"
    elif len(warnings) >= 2:
        risk_level = "medium"
    else:
        risk_level = "low"

    return {"warnings": warnings, "errors": errors, "risk_level": risk_level}


def _to_float(value) -> float:
    """Parse numeric values with zero fallback."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0
