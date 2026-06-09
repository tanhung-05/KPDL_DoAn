"""Shared constants for paths, expected columns, defaults, and session keys."""

from pathlib import Path

APP_OUTPUTS_DIR = Path("app_outputs")

REQUIRED_COLUMNS = [
    "InvoiceNo",
    "StockCode",
    "Quantity",
    "UnitPrice",
    "InvoiceDate",
]

OPTIONAL_COLUMNS = ["Description"]

SESSION_STATE_KEYS = [
    "raw_df",
    "temporal_db",
    "item_mapping",
    "preprocess_report",
    "tx_before_filter",
    "tx_after_filter",
    "phase1_output",
    "phase2_output",
    "phase3_report",
    "modified_transactions_df",
]

DEFAULT_MAX_TRANSACTION_LEN = 30
DEFAULT_MINING_RATIO = 0.01
DEFAULT_SENSITIVE_RATIO = 0.015
DEFAULT_CANDIDATE_MINING_RATIO = 0.015
DEFAULT_MIN_PEAKNESS_RATIO = 1.5
DEFAULT_MIN_SUPPORT_WINDOWS = 2
DEFAULT_MAX_SELECTED_PER_WINDOW = 30

OUTPUT_FILES = {
    "temporal_db": APP_OUTPUTS_DIR / "temporal_db.json",
    "item_mapping": APP_OUTPUTS_DIR / "item_mapping.json",
    "phase1_peak_shui": APP_OUTPUTS_DIR / "phase1_peak_shui.json",
    "phase2_sanitized_db": APP_OUTPUTS_DIR / "phase2_sanitized_db.json",
    "phase2_summary": APP_OUTPUTS_DIR / "phase2_summary.json",
    "phase3_verification_report": APP_OUTPUTS_DIR / "phase3_verification_report.json",
    "phase3_window_metrics": APP_OUTPUTS_DIR / "phase3_window_metrics.csv",
    "phase3_pattern_metrics": APP_OUTPUTS_DIR / "phase3_pattern_metrics.csv",
    "modified_transactions": APP_OUTPUTS_DIR / "modified_transactions.csv",
    "sanitized_retail": APP_OUTPUTS_DIR / "sanitized_retail.txt",
}
