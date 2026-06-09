"""Pydantic response models for the backend API."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class HealthResponse(BaseModel):
    """Health check response."""

    status: str
    service: str


class DatasetResponse(BaseModel):
    """Response returned after creating a dataset run."""

    model_config = ConfigDict(populate_by_name=True)

    run_id: str
    source: str
    csv_schema: dict[str, Any] = Field(alias="schema")
    raw_summary: dict[str, Any]
    preview: list[dict[str, Any]]


class CompletedResultsResponse(BaseModel):
    """Response returned after uploading completed pipeline artifacts."""

    run_id: str
    source: str
    uploaded_files: list[str]
    recognized_files: list[str]
    missing_recommended: list[str]
    validation_warnings: list[str]
    outputs: list[str]


class RawSummaryResponse(BaseModel):
    """Detailed raw-data summary for a run."""

    model_config = ConfigDict(populate_by_name=True)

    run_id: str
    csv_schema: dict[str, Any] = Field(alias="schema")
    raw_summary: dict[str, Any]
    monthly_stats: list[dict[str, Any]]
    top_products: list[dict[str, Any]]
    top_products_by_quantity: list[dict[str, Any]] = Field(default_factory=list)
    product_table: list[dict[str, Any]] = Field(default_factory=list)
    preview: list[dict[str, Any]]


class PreprocessRequest(BaseModel):
    """Preprocessing parameters."""

    max_transaction_len: int | None = 30
    window_granularity: str = "M"
    utility_mode: str = "round"


class PreprocessResponse(BaseModel):
    """Preprocessing result summary."""

    run_id: str
    preprocess_report: dict[str, Any]
    temporal_metadata: dict[str, Any]
    tx_before_filter_preview: list[dict[str, Any]]
    tx_after_filter_preview: list[dict[str, Any]]
    max_len_impact: list[dict[str, Any]]
    outputs: list[str]


class Phase1Request(BaseModel):
    """Phase 1 mining parameters."""

    mining_ratio: float = 0.01
    sensitive_ratio: float = 0.015
    candidate_mining_ratio: float = 0.015
    min_peakness_ratio: float = 1.5
    min_support_windows: int = 2
    max_selected_per_window: int = 30
    max_patterns_per_window: int = 3000
    enable_twu_pruning: bool = True


class Phase1Response(BaseModel):
    """Phase 1 mining response."""

    run_id: str
    mining_summary: dict[str, Any]
    selected_shuis: list[dict[str, Any]]
    item_scores_flat: list[dict[str, Any]]
    outputs: list[str]


class Phase2Request(BaseModel):
    """Phase 2 sanitization parameters."""

    local_ratio: float = 0.015
    global_ratio: float = 0.015
    global_beta: float = 0.25
    global_gamma: float = 0.75
    selected_pattern_keys: list[str] | None = None


class Phase2Response(BaseModel):
    """Phase 2 sanitization response."""

    run_id: str
    summary: dict[str, Any]
    local_reports: list[dict[str, Any]]
    modifications_preview: list[dict[str, Any]]
    modified_transactions_preview: list[dict[str, Any]]
    outputs: list[str]


class Phase3Request(BaseModel):
    """Phase 3 verification parameters."""

    local_ratio: float = 0.015
    global_ratio: float = 0.015


class Phase3Response(BaseModel):
    """Phase 3 verification response."""

    run_id: str
    report: dict[str, Any]
    window_metrics: list[dict[str, Any]]
    pattern_metrics: list[dict[str, Any]]
    modified_transactions_preview: list[dict[str, Any]]
    outputs: list[str]


class RunStatusResponse(BaseModel):
    """Minimal run status for frontend polling."""

    run_id: str
    exists: bool
    outputs: list[str]


class OutputsResponse(BaseModel):
    """Available output files for a run."""

    run_id: str
    outputs: list[dict[str, Any]]


class ExplorerResponse(BaseModel):
    """Explorer data for modified transactions and sensitive patterns."""

    run_id: str
    modified_transactions: list[dict[str, Any]]
    selected_patterns: list[dict[str, Any]]
    window_metrics: list[dict[str, Any]]
    pattern_metrics: list[dict[str, Any]]
    phase0_summary: dict[str, Any] = Field(default_factory=dict)
    phase2_summary: dict[str, Any] = Field(default_factory=dict)
    comparison_summary: dict[str, Any] = Field(default_factory=dict)
    comparison_tables: dict[str, list[dict[str, Any]]] = Field(default_factory=dict)


class TransactionDetailResponse(BaseModel):
    """Before/after item-level transaction detail."""

    run_id: str
    window: str
    tid: str
    original: dict[str, Any] | None
    sanitized: dict[str, Any] | None
    item_rows: list[dict[str, Any]]
