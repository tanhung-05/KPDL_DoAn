"""FastAPI entry point for the first TA-PPHUIM migration slice."""

from __future__ import annotations

import json
import zipfile
from io import BytesIO
from pathlib import Path
from typing import Any

import pandas as pd
from json import JSONDecodeError
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from backend.app import storage
from backend.app.schemas import (
    CompletedResultsResponse,
    DatasetResponse,
    ExplorerResponse,
    HealthResponse,
    OutputsResponse,
    Phase1Request,
    Phase1Response,
    Phase2Request,
    Phase2Response,
    Phase3Request,
    Phase3Response,
    PreprocessRequest,
    PreprocessResponse,
    RawSummaryResponse,
    RunStatusResponse,
    TransactionDetailResponse,
)
from modules.efim_runner import check_pami_available
from modules.loader import load_csv, normalize_column_names, validate_schema
from modules.mapping_utils import normalize_item_mapping, pattern_to_labels
from modules.preprocessing import compute_max_len_impact, preprocess_retail_df
from modules.phase1_mining import phase1_mine
from modules.phase2_sanitization import phase2_sanitize
from modules.phase3_verification import phase3_verify
from modules.raw_analysis import (
    build_raw_monthly_stats,
    build_product_table,
    build_top_products_by_quantity,
    build_top_products_by_utility,
    compute_raw_summary,
)
from modules.sample_data import generate_synthetic_retail_data


app = FastAPI(
    title="TA-PPHUIM Backend",
    version="0.1.0",
    description="Backend migration layer for the TA-PPHUIM demo pipeline.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"^http://(localhost|127\.0\.0\.1):\d+$",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

SUPPORTED_RESULT_EXTENSIONS = {".json", ".csv", ".xlsx", ".txt", ".zip"}
TEMPORAL_DB_UPLOAD_NAMES = {
    "temporal_db.json",
    "temporal_db_filtered.json",
    "temporal_db_original.json",
}
COMPARISON_CSV_FILES = [
    "00_high_level_summary.csv",
    "01_static_efim_hui.csv",
    "02_temporal_selected_pshui.csv",
    "03_static_vs_temporal.csv",
    "04_static_vs_temporal_summary.csv",
    "05_phase2_summary.csv",
    "06_phase2_window_summary.csv",
    "07_method_static_vs_temporal.csv",
    "08_algorithm_comparison.csv",
]
RECOMMENDED_COMPLETED_FILES = [
    "temporal_db_filtered.json",
    "phase1_peak_shui.json",
    "phase2_summary.json",
    "phase2_sanitized_db.json",
    "comparison_report.json",
]


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    """Return backend liveness information."""
    return HealthResponse(status="ok", service="ta-pphuim-backend")


@app.get("/")
def product_home() -> dict[str, Any]:
    """Return a business-facing API landing payload."""
    return {
        "app": "Retail Insight & Privacy",
        "subtitle": (
            "Phân tích dữ liệu bán hàng, tìm combo sản phẩm giá trị cao "
            "và bảo vệ mẫu kinh doanh nhạy cảm trước khi chia sẻ dữ liệu."
        ),
        "pipeline": [
            "Upload dữ liệu",
            "Phân tích doanh thu",
            "Tìm combo",
            "Gợi ý bán kèm",
            "Chọn combo nhạy cảm",
            "Bảo vệ dữ liệu",
            "Tải báo cáo",
        ],
    }


@app.post("/datasets/upload", response_model=DatasetResponse)
async def upload_dataset(file: UploadFile = File(...)) -> DatasetResponse:
    """Upload and validate a retail transaction CSV."""
    if not file.filename or not file.filename.lower().endswith(".csv"):
        raise HTTPException(status_code=400, detail="Vui lòng upload file CSV.")

    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="File CSV đang trống.")

    try:
        raw_df = normalize_column_names(load_csv(BytesIO(content)))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Không đọc được CSV: {exc}") from exc
    except Exception as exc:  # pragma: no cover - defensive API boundary
        raise HTTPException(status_code=400, detail=f"Không đọc được CSV: {exc}") from exc

    return _create_dataset_response(raw_df, source="uploaded_csv")


@app.post("/upload-sales-data", response_model=DatasetResponse)
async def upload_sales_data(file: UploadFile = File(...)) -> DatasetResponse:
    """Friendly alias for uploading retail sales CSV data."""
    return await upload_dataset(file)


@app.post("/datasets/demo", response_model=DatasetResponse)
def create_demo_dataset(
    num_rows: int = 1500,
    months: int = 6,
    seed: int = 42,
) -> DatasetResponse:
    """Create a synthetic demo dataset run."""
    try:
        raw_df = generate_synthetic_retail_data(
            num_rows=num_rows,
            months=months,
            seed=seed,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return _create_dataset_response(raw_df, source="synthetic_demo")


@app.post("/results/upload", response_model=CompletedResultsResponse)
async def upload_completed_results(files: list[UploadFile] = File(...)) -> CompletedResultsResponse:
    """Upload completed pipeline artifacts without running EFIM or sanitization."""
    if not files:
        raise HTTPException(status_code=400, detail="Vui lòng upload ít nhất một file kết quả.")

    run_id = storage.create_run(source="completed_results")
    run_dir = storage.require_run_dir(run_id)
    uploaded_files: list[str] = []
    validation_warnings: list[str] = []

    for file in files:
        file_name = _safe_upload_name(file.filename)
        suffix = Path(file_name).suffix.lower()
        if suffix not in SUPPORTED_RESULT_EXTENSIONS:
            validation_warnings.append(f"Bỏ qua file không hỗ trợ: {file_name}")
            continue

        content = await file.read()
        if not content:
            validation_warnings.append(f"File rỗng: {file_name}")
            continue

        try:
            if suffix == ".zip":
                extracted = _extract_completed_zip(content, run_dir)
                uploaded_files.extend(extracted)
            else:
                target = _safe_run_output_path(run_dir, file_name)
                target.write_bytes(content)
                uploaded_files.append(file_name)
        except (ValueError, zipfile.BadZipFile) as exc:
            validation_warnings.append(f"Không thể xử lý {file_name}: {exc}")

    _create_completed_aliases(run_dir, uploaded_files)
    recognized_files = _detect_completed_files(run_dir)
    validation_warnings.extend(_validate_completed_outputs(run_dir, recognized_files))
    missing_recommended = [
        file_name for file_name in RECOMMENDED_COMPLETED_FILES
        if file_name not in recognized_files
    ]

    storage.write_json(
        run_id,
        "completed_results_manifest.json",
        {
            "run_id": run_id,
            "source": "completed_results",
            "uploaded_files": uploaded_files,
            "recognized_files": recognized_files,
            "missing_recommended": missing_recommended,
            "validation_warnings": validation_warnings,
        },
    )

    return CompletedResultsResponse(
        run_id=run_id,
        source="completed_results",
        uploaded_files=uploaded_files,
        recognized_files=recognized_files,
        missing_recommended=missing_recommended,
        validation_warnings=validation_warnings,
        outputs=storage.list_outputs(run_id),
    )


@app.get("/datasets/{run_id}/raw-summary", response_model=RawSummaryResponse)
def get_raw_summary(run_id: str) -> RawSummaryResponse:
    """Return raw-data summary and light chart data for a run."""
    try:
        raw_df = storage.load_raw_dataframe(run_id)
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    schema = validate_schema(raw_df)
    if not schema["is_valid"]:
        raise HTTPException(
            status_code=422,
            detail="Dataset thiếu cột bắt buộc: " + ", ".join(schema["missing_columns"]),
        )

    return RawSummaryResponse(
        run_id=run_id,
        csv_schema=schema,
        raw_summary=_json_safe(compute_raw_summary(raw_df)),
        monthly_stats=_dataframe_records(build_raw_monthly_stats(raw_df)),
        top_products=_dataframe_records(build_top_products_by_utility(raw_df, top_n=10)),
        top_products_by_quantity=_dataframe_records(build_top_products_by_quantity(raw_df, top_n=10)),
        product_table=_dataframe_records(build_product_table(raw_df, top_n=100)),
        preview=_dataframe_records(raw_df.head(20)),
    )


@app.get("/sales-overview", response_model=RawSummaryResponse)
def sales_overview(run_id: str) -> RawSummaryResponse:
    """Friendly alias for the sales overview dashboard payload."""
    return get_raw_summary(run_id)


@app.post("/preprocessing/{run_id}", response_model=PreprocessResponse)
def run_preprocessing(
    run_id: str,
    request: PreprocessRequest = PreprocessRequest(),
) -> PreprocessResponse:
    """Run Phase 0 preprocessing for a dataset run."""
    try:
        raw_df = storage.load_raw_dataframe(run_id)
        (
            temporal_db,
            item_mapping,
            preprocess_report,
            tx_before_filter,
            tx_after_filter,
        ) = preprocess_retail_df(
            raw_df,
            max_transaction_len=request.max_transaction_len,
            window_granularity=request.window_granularity,
            utility_mode=request.utility_mode,
        )
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    output_dir = storage.require_run_dir(run_id)
    _write_json_file(output_dir / "temporal_db.json", temporal_db)
    _write_json_file(output_dir / "item_mapping.json", item_mapping)
    storage.write_json(run_id, "preprocess_report.json", preprocess_report)
    tx_before_filter.to_csv(output_dir / "tx_before_filter.csv", index=False)
    tx_after_filter.to_csv(output_dir / "tx_after_filter.csv", index=False)
    impact_df = compute_max_len_impact(tx_before_filter)

    return PreprocessResponse(
        run_id=run_id,
        preprocess_report=_json_safe(preprocess_report),
        temporal_metadata=_json_safe(temporal_db.get("metadata", {})),
        tx_before_filter_preview=_dataframe_records(tx_before_filter.head(50)),
        tx_after_filter_preview=_dataframe_records(tx_after_filter.head(50)),
        max_len_impact=_dataframe_records(impact_df),
        outputs=storage.list_outputs(run_id),
    )


@app.get("/phase1/pami-status")
def get_pami_status() -> dict[str, Any]:
    """Return PAMI/EFIM availability."""
    return check_pami_available()


@app.post("/phase1/{run_id}/mine", response_model=Phase1Response)
def run_phase1(
    run_id: str,
    request: Phase1Request = Phase1Request(),
) -> Phase1Response:
    """Run Phase 1 EFIM mining and PSHUI selection."""
    availability = check_pami_available()
    if not availability["available"]:
        raise HTTPException(
            status_code=503,
            detail=(
                f"Chưa cài PAMI EFIM. {availability['install_hint']} "
                f"Lỗi import: {availability['error']}"
            ),
        )

    try:
        temporal_db = storage.read_json(run_id, "temporal_db.json")
        item_mapping = storage.read_json(run_id, "item_mapping.json")
        phase1_output = phase1_mine(
            temporal_db,
            item_mapping,
            request.model_dump(),
            output_dir=storage.require_run_dir(run_id),
        )
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=409,
            detail="Cần chạy preprocessing trước khi chạy Phase 1.",
        ) from exc
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return Phase1Response(
        run_id=run_id,
        mining_summary=_json_safe(phase1_output.get("mining_summary", {})),
        selected_shuis=_json_safe(phase1_output.get("selected_shuis", [])),
        item_scores_flat=_json_safe(phase1_output.get("item_scores_flat", [])),
        outputs=storage.list_outputs(run_id),
    )


@app.post("/phase2/{run_id}/sanitize", response_model=Phase2Response)
def run_phase2(
    run_id: str,
    request: Phase2Request = Phase2Request(),
) -> Phase2Response:
    """Run Phase 2 sanitization."""
    try:
        temporal_db = storage.read_json(run_id, "temporal_db.json")
        item_mapping = storage.read_json(run_id, "item_mapping.json")
        phase1_output = storage.read_json(run_id, "phase1_peak_shui.json")
        phase1_output = _filter_phase1_selected_patterns(phase1_output, request.selected_pattern_keys)
        phase2_output, summary, modified_transactions_df = phase2_sanitize(
            phase1_output=phase1_output,
            temporal_db=temporal_db,
            item_mapping=item_mapping,
            local_ratio=request.local_ratio,
            global_ratio=request.global_ratio,
            output_dir=storage.require_run_dir(run_id),
            global_beta=request.global_beta,
            global_gamma=request.global_gamma,
        )
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=409,
            detail="Cần chạy preprocessing và Phase 1 trước khi chạy Phase 2.",
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return Phase2Response(
        run_id=run_id,
        summary=_json_safe(summary),
        local_reports=_json_safe(phase2_output.get("local_reports", [])),
        modifications_preview=_json_safe(phase2_output.get("modifications", [])[:50]),
        modified_transactions_preview=_dataframe_records(modified_transactions_df.head(50)),
        outputs=storage.list_outputs(run_id),
    )


@app.post("/select-sensitive-combos")
def select_sensitive_combos(run_id: str, pattern_keys: list[str]) -> dict[str, Any]:
    """Persist a simple manifest of user-selected sensitive combo keys."""
    try:
        storage.write_json(
            run_id,
            "selected_sensitive_combos.json",
            {"run_id": run_id, "selected_pattern_keys": pattern_keys},
        )
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"run_id": run_id, "selected_count": len(pattern_keys)}


@app.post("/phase3/{run_id}/verify", response_model=Phase3Response)
def run_phase3(
    run_id: str,
    request: Phase3Request = Phase3Request(),
) -> Phase3Response:
    """Run Phase 3 verification."""
    try:
        temporal_db = storage.read_json(run_id, "temporal_db.json")
        item_mapping = storage.read_json(run_id, "item_mapping.json")
        phase1_output = storage.read_json(run_id, "phase1_peak_shui.json")
        phase2_output = {
            "metadata": storage.read_json(run_id, "phase2_summary.json"),
            "sanitized_db": storage.read_json(run_id, "phase2_sanitized_db.json"),
        }
        report, window_metrics_df, pattern_metrics_df, modified_transactions_df = phase3_verify(
            phase1_output=phase1_output,
            original_db=temporal_db,
            phase2_output=phase2_output,
            item_mapping=item_mapping,
            local_ratio=request.local_ratio,
            global_ratio=request.global_ratio,
            output_dir=storage.require_run_dir(run_id),
        )
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=409,
            detail="Cần chạy Phase 2 trước khi chạy Phase 3.",
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return Phase3Response(
        run_id=run_id,
        report=_json_safe(report),
        window_metrics=_dataframe_records(window_metrics_df),
        pattern_metrics=_dataframe_records(pattern_metrics_df),
        modified_transactions_preview=_dataframe_records(modified_transactions_df.head(50)),
        outputs=storage.list_outputs(run_id),
    )


@app.get("/runs/{run_id}/status", response_model=RunStatusResponse)
def get_run_status(run_id: str) -> RunStatusResponse:
    """Return a minimal status object for a run."""
    try:
        outputs = storage.list_outputs(run_id)
    except (FileNotFoundError, ValueError):
        return RunStatusResponse(run_id=run_id, exists=False, outputs=[])
    return RunStatusResponse(run_id=run_id, exists=True, outputs=outputs)


@app.get("/runs/{run_id}/outputs", response_model=OutputsResponse)
def get_run_outputs(run_id: str) -> OutputsResponse:
    """Return output file metadata for a run."""
    try:
        run_path = storage.require_run_dir(run_id)
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    outputs = []
    for path in sorted(run_path.iterdir()):
        if path.is_file():
            outputs.append(
                {
                    "file_name": path.name,
                    "size_bytes": path.stat().st_size,
                    "download_url": f"/exports/{run_id}/{path.name}",
                }
            )
    return OutputsResponse(run_id=run_id, outputs=outputs)


@app.get("/runs/{run_id}/explorer", response_model=ExplorerResponse)
def get_explorer_data(run_id: str) -> ExplorerResponse:
    """Return compact explorer data for the React UI."""
    try:
        storage.require_run_dir(run_id)
        item_mapping = _optional_json(run_id, "item_mapping.json")
        phase1_output = _optional_json(run_id, "phase1_peak_shui.json")
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    selected_patterns = _selected_patterns_for_api(phase1_output, item_mapping)
    modified_transactions = _optional_csv_records(run_id, "modified_transactions.csv")
    window_metrics = _optional_csv_records(run_id, "phase3_window_metrics.csv")
    pattern_metrics = _optional_csv_records(run_id, "phase3_pattern_metrics.csv")
    phase0_summary = _phase0_summary_for_api(_optional_json(run_id, "temporal_db.json"))
    phase2_summary = _optional_json(run_id, "phase2_summary.json")
    comparison_summary = _comparison_summary_for_api(_optional_json(run_id, "comparison_report.json"))
    comparison_tables = {
        file_name: _optional_csv_records(run_id, file_name)
        for file_name in COMPARISON_CSV_FILES
    }

    return ExplorerResponse(
        run_id=run_id,
        modified_transactions=modified_transactions,
        selected_patterns=selected_patterns,
        window_metrics=window_metrics,
        pattern_metrics=pattern_metrics,
        phase0_summary=_json_safe(phase0_summary),
        phase2_summary=_json_safe(phase2_summary),
        comparison_summary=_json_safe(comparison_summary),
        comparison_tables=_json_safe(comparison_tables),
    )


@app.get("/runs/{run_id}/transactions/{window}/{tid}", response_model=TransactionDetailResponse)
def get_transaction_detail(run_id: str, window: str, tid: str) -> TransactionDetailResponse:
    """Return before/after detail for one transaction."""
    try:
        original_db = storage.read_json(run_id, "temporal_db.json")
        item_mapping = _optional_json(run_id, "item_mapping.json")
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    sanitized_db = _optional_json(run_id, "phase2_sanitized_db.json")
    original_tx = _find_transaction(original_db, window, tid)
    sanitized_tx = _find_transaction(sanitized_db, window, tid)

    if original_tx is None and sanitized_tx is None:
        raise HTTPException(status_code=404, detail="Không tìm thấy giao dịch.")

    return TransactionDetailResponse(
        run_id=run_id,
        window=str(window),
        tid=str(tid),
        original=original_tx,
        sanitized=sanitized_tx,
        item_rows=_transaction_item_rows(original_tx, sanitized_tx, item_mapping),
    )


@app.get("/exports/{run_id}/{file_name}")
def download_output(run_id: str, file_name: str) -> FileResponse:
    """Download one generated run output."""
    try:
        path = storage.output_path(run_id, file_name)
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=404, detail="Không tìm thấy file output.")
    return FileResponse(path, filename=file_name)


def _safe_upload_name(file_name: str | None) -> str:
    """Return a safe basename for an uploaded artifact."""
    safe_name = Path(file_name or "").name
    if not safe_name or safe_name in {".", ".."}:
        raise HTTPException(status_code=400, detail="Tên file upload không hợp lệ.")
    return safe_name


def _safe_run_output_path(run_dir: Path, relative_name: str) -> Path:
    """Return a path inside run_dir and reject traversal attempts."""
    normalized = Path(relative_name)
    if normalized.is_absolute() or any(part in {"..", ""} for part in normalized.parts):
        raise ValueError("Đường dẫn trong file upload không hợp lệ.")
    target = (run_dir / normalized).resolve()
    run_root = run_dir.resolve()
    if target != run_root and run_root not in target.parents:
        raise ValueError("File upload cố ghi ra ngoài thư mục run.")
    target.parent.mkdir(parents=True, exist_ok=True)
    return target


def _extract_completed_zip(content: bytes, run_dir: Path) -> list[str]:
    """Safely extract supported completed-result files from a zip archive."""
    extracted: list[str] = []
    with zipfile.ZipFile(BytesIO(content)) as archive:
        for member in archive.infolist():
            if member.is_dir():
                continue
            relative = Path(member.filename)
            if relative.is_absolute() or any(part in {"..", ""} for part in relative.parts):
                continue
            if relative.suffix.lower() not in SUPPORTED_RESULT_EXTENSIONS - {".zip"}:
                continue
            target = _safe_run_output_path(run_dir, str(relative))
            with archive.open(member) as source:
                target.write_bytes(source.read())
            extracted.append(str(relative).replace("\\", "/"))
    return extracted


def _create_completed_aliases(run_dir: Path, uploaded_files: list[str]) -> None:
    """Create canonical aliases expected by existing pipeline viewers."""
    basenames = {Path(file_name).name.lower(): file_name for file_name in uploaded_files}
    if "temporal_db.json" not in basenames:
        for candidate in ["temporal_db_filtered.json", "temporal_db_original.json"]:
            source_name = basenames.get(candidate)
            if source_name:
                source = _safe_run_output_path(run_dir, source_name)
                if source.exists():
                    (run_dir / "temporal_db.json").write_bytes(source.read_bytes())
                    uploaded_files.append("temporal_db.json")
                    break


def _detect_completed_files(run_dir: Path) -> list[str]:
    """Detect known completed-result files by basename."""
    known_names = set(RECOMMENDED_COMPLETED_FILES)
    known_names.update(TEMPORAL_DB_UPLOAD_NAMES)
    known_names.update(COMPARISON_CSV_FILES)
    known_names.update(
        {
            "item_mapping.json",
            "retail_filtered_spmf.txt",
            "phase2_sanitized_db.json",
            "phase2_summary.json",
            "comparison_report.xlsx",
            "modified_transactions.csv",
            "phase3_window_metrics.csv",
            "phase3_pattern_metrics.csv",
        }
    )
    found = []
    for path in run_dir.rglob("*"):
        if path.is_file() and path.name in known_names:
            found.append(path.name)
    return sorted(set(found))


def _validate_completed_outputs(run_dir: Path, recognized_files: list[str]) -> list[str]:
    """Validate uploaded completed artifacts without making the app crash."""
    warnings: list[str] = []
    for file_name in TEMPORAL_DB_UPLOAD_NAMES:
        if file_name in recognized_files:
            data = _read_json_from_run_dir(run_dir, file_name, warnings)
            if data and not ("metadata" in data and "windows" in data):
                warnings.append(f"{file_name} thiếu field metadata hoặc windows.")

    if "phase1_peak_shui.json" in recognized_files:
        data = _read_json_from_run_dir(run_dir, "phase1_peak_shui.json", warnings)
        if data and not _looks_like_phase1_output(data):
            warnings.append("phase1_peak_shui.json không giống schema Phase 1 mong đợi.")

    if "phase2_summary.json" in recognized_files:
        data = _read_json_from_run_dir(run_dir, "phase2_summary.json", warnings)
        phase2_keys = {
            "utility_loss_rate",
            "utility_loss_percent",
            "local_violations_after_patch",
            "local_violations_after",
            "post_patch_leaks",
            "post_patch_global_leaks",
        }
        if data and not any(key in data for key in phase2_keys):
            warnings.append("phase2_summary.json chưa thấy các chỉ số Phase 2 quan trọng.")

    if "comparison_report.json" in recognized_files:
        data = _read_json_from_run_dir(run_dir, "comparison_report.json", warnings)
        if data and "high_level_summary" not in data:
            warnings.append("comparison_report.json không có high_level_summary.")

    return warnings


def _read_json_from_run_dir(run_dir: Path, file_name: str, warnings: list[str]) -> dict[str, Any]:
    """Read a JSON artifact in a run dir and collect warnings on failure."""
    paths = [path for path in run_dir.rglob(file_name) if path.is_file()]
    if not paths:
        return {}
    try:
        return json.loads(paths[0].read_text(encoding="utf-8"))
    except (OSError, JSONDecodeError) as exc:
        warnings.append(f"Không đọc được {file_name}: {exc}")
        return {}


def _looks_like_phase1_output(data: dict[str, Any]) -> bool:
    """Return True when a payload is compatible with Phase 1 display."""
    if data.get("selected_shuis"):
        return True
    windows = data.get("windows", {})
    if isinstance(windows, dict):
        if data.get("metadata") and windows:
            return True
        return any(payload.get("selected_shuis") for payload in windows.values() if isinstance(payload, dict))
    return False


def _create_dataset_response(raw_df: pd.DataFrame, source: str) -> DatasetResponse:
    """Validate, persist, and summarize a dataset."""
    schema = validate_schema(raw_df)
    if not schema["is_valid"]:
        raise HTTPException(
            status_code=422,
            detail="CSV thiếu cột bắt buộc: " + ", ".join(schema["missing_columns"]),
        )

    run_id = storage.create_run(source=source)
    storage.save_raw_dataframe(run_id, raw_df)
    raw_summary = _json_safe(compute_raw_summary(raw_df))
    storage.write_json(
        run_id,
        "raw_summary.json",
        {
            "schema": schema,
            "raw_summary": raw_summary,
        },
    )

    return DatasetResponse(
        run_id=run_id,
        source=source,
        csv_schema=schema,
        raw_summary=raw_summary,
        preview=_dataframe_records(raw_df.head(20)),
    )


def _write_json_file(path, payload: dict[str, Any]) -> None:
    """Write a JSON artifact."""
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _optional_json(run_id: str, file_name: str) -> dict[str, Any]:
    """Read a JSON output if it exists, otherwise return an empty dict."""
    try:
        return storage.read_json(run_id, file_name)
    except FileNotFoundError:
        try:
            run_dir = storage.require_run_dir(run_id)
        except (FileNotFoundError, ValueError):
            return {}
        paths = [path for path in run_dir.rglob(file_name) if path.is_file()]
        if not paths:
            return {}
        try:
            return json.loads(paths[0].read_text(encoding="utf-8"))
        except (OSError, JSONDecodeError):
            return {}


def _optional_csv_records(run_id: str, file_name: str) -> list[dict[str, Any]]:
    """Read a CSV output if it exists, otherwise return an empty list."""
    try:
        path = storage.output_path(run_id, file_name)
    except (FileNotFoundError, ValueError):
        return []
    if not path.exists():
        run_dir = storage.require_run_dir(run_id)
        paths = [candidate for candidate in run_dir.rglob(file_name) if candidate.is_file()]
        if not paths:
            return []
        path = paths[0]
    return _dataframe_records(pd.read_csv(path))


def _phase0_summary_for_api(temporal_db: dict[str, Any]) -> dict[str, Any]:
    """Build a compact Phase 0 summary from temporal_db."""
    if not temporal_db:
        return {}
    windows = temporal_db.get("windows", {})
    total_transactions = 0
    total_utility = 0
    item_ids: set[int] = set()
    for window_payload in windows.values() if isinstance(windows, dict) else []:
        transactions = window_payload.get("transactions", [])
        total_transactions += len(transactions)
        total_utility += int(window_payload.get("total_utility", 0) or 0)
        for tx in transactions:
            for item in tx.get("items", []):
                try:
                    item_ids.add(int(item))
                except (TypeError, ValueError):
                    continue
    return {
        "num_windows": len(windows) if isinstance(windows, dict) else 0,
        "num_transactions": total_transactions,
        "num_items": len(item_ids),
        "total_utility": total_utility,
        "metadata": temporal_db.get("metadata", {}),
    }


def _comparison_summary_for_api(comparison_report: dict[str, Any]) -> dict[str, Any]:
    """Extract a high-level comparison summary for dashboard rendering."""
    if not comparison_report:
        return {}
    summary = comparison_report.get("high_level_summary")
    if isinstance(summary, dict):
        return summary
    if isinstance(summary, list) and summary:
        first = summary[0]
        return first if isinstance(first, dict) else {"high_level_summary": summary}
    return comparison_report


def _selected_patterns_for_api(phase1_output: dict, item_mapping: dict | None) -> list[dict[str, Any]]:
    """Flatten and enrich Phase 1 selected patterns for the frontend."""
    selected = list(phase1_output.get("selected_shuis", [])) if phase1_output else []
    if not selected and phase1_output:
        for window_payload in phase1_output.get("windows", {}).values():
            selected.extend(window_payload.get("selected_shuis", []))

    rows = []
    for pattern in selected:
        items = [int(item) for item in pattern.get("items", [])]
        rows.append(
            {
                "window": pattern.get("selected_window"),
                "pattern_key": pattern.get("pattern_key") or " ".join(str(item) for item in items),
                "items": items,
                "product_labels": pattern_to_labels(items, item_mapping),
                "window_utility": pattern.get("window_utility"),
                "window_ratio": pattern.get("window_ratio"),
                "support_windows": pattern.get("support_windows"),
                "peakness_ratio": pattern.get("peakness_ratio"),
                "peak_windows": pattern.get("peak_windows", []),
            }
        )
    return _json_safe(rows)


def _filter_phase1_selected_patterns(
    phase1_output: dict[str, Any],
    selected_pattern_keys: list[str] | None,
) -> dict[str, Any]:
    """Return a copy of Phase 1 output limited to user-selected pattern keys."""
    if not selected_pattern_keys:
        return phase1_output

    selected_keys = {str(key) for key in selected_pattern_keys if str(key)}
    if not selected_keys:
        return phase1_output

    filtered = json.loads(json.dumps(phase1_output))

    def keep(pattern: dict[str, Any]) -> bool:
        pattern_key = pattern.get("pattern_key")
        if not pattern_key:
            items = pattern.get("items", [])
            pattern_key = " ".join(str(item) for item in items)
        return str(pattern_key) in selected_keys

    if isinstance(filtered.get("selected_shuis"), list):
        filtered["selected_shuis"] = [
            pattern for pattern in filtered["selected_shuis"]
            if isinstance(pattern, dict) and keep(pattern)
        ]

    windows = filtered.get("windows", {})
    if isinstance(windows, dict):
        for window_payload in windows.values():
            if isinstance(window_payload, dict) and isinstance(window_payload.get("selected_shuis"), list):
                window_payload["selected_shuis"] = [
                    pattern for pattern in window_payload["selected_shuis"]
                    if isinstance(pattern, dict) and keep(pattern)
                ]

    return filtered


def _find_transaction(db: dict | None, window: str, tid: str) -> dict[str, Any] | None:
    """Find one transaction in a temporal DB payload."""
    if not isinstance(db, dict):
        return None
    window_payload = db.get("windows", {}).get(str(window), {})
    for tx in window_payload.get("transactions", []):
        if str(tx.get("tid", "")) == str(tid):
            return tx
    return None


def _transaction_item_rows(
    original_tx: dict[str, Any] | None,
    sanitized_tx: dict[str, Any] | None,
    item_mapping: dict | None,
) -> list[dict[str, Any]]:
    """Build item-level before/after rows for a transaction."""
    mapping = normalize_item_mapping(item_mapping)
    before_utils = _item_utils(original_tx)
    after_utils = _item_utils(sanitized_tx)
    item_ids = sorted(set(before_utils) | set(after_utils))
    rows = []
    for item_id in item_ids:
        item_meta = mapping.get(item_id, {})
        before = int(before_utils.get(item_id, 0))
        after = int(after_utils.get(item_id, 0))
        rows.append(
            {
                "item_id": item_id,
                "stock_code": item_meta.get("stock_code", str(item_id)),
                "description": item_meta.get("description", ""),
                "before_utility": before,
                "after_utility": after,
                "delta": before - after,
            }
        )
    return rows


def _item_utils(tx: dict[str, Any] | None) -> dict[int, int]:
    """Return item utilities keyed by integer item id."""
    if not isinstance(tx, dict):
        return {}
    result = {}
    for item, utility in tx.get("item_utils", {}).items():
        try:
            result[int(item)] = int(utility)
        except (TypeError, ValueError):
            continue
    return result


def _dataframe_records(df: pd.DataFrame) -> list[dict[str, Any]]:
    """Convert a DataFrame to JSON-safe records."""
    if df.empty:
        return []
    return json.loads(df.to_json(orient="records", date_format="iso"))


def _json_safe(payload: Any) -> Any:
    """Round-trip through JSON so NumPy/Pandas scalars become API-safe values."""
    return json.loads(json.dumps(payload, default=_json_default))


def _json_default(value: Any) -> Any:
    """Serialize values not handled by the standard JSON encoder."""
    if hasattr(value, "item"):
        return value.item()
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)
