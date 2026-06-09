"""Preprocessing utilities for temporal transaction windows.

This module converts raw retail rows into the temporal transaction database
consumed by later TA-PPHUIM phases. It contains no UI code.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import pandas as pd

from modules.constants import REQUIRED_COLUMNS


@dataclass(frozen=True)
class PreprocessConfig:
    """Configuration for building the temporal transaction database."""

    max_transaction_len: Optional[int] = 30
    window_granularity: str = "M"
    utility_mode: str = "round"


def preprocess_retail_df(
    df: pd.DataFrame,
    max_transaction_len: Optional[int] = 30,
    window_granularity: str = "M",
    utility_mode: str = "round",
) -> tuple[dict, dict, dict, pd.DataFrame, pd.DataFrame]:
    """Clean raw retail rows and build a temporal transaction database.

    Returns:
        ``(temporal_db, item_mapping, preprocess_report, tx_before_filter,
        tx_after_filter)``.

    ``temporal_db`` has this schema:
        ``{"metadata": {...}, "windows": {"YYYY-MM": {"window_key": str,
        "total_utility": int, "num_transactions": int, "transactions": [...]}}}``

    Transactions contain ``tid``, ``invoice_no``, ``window``, ``items``,
    ``item_utils`` with string item-id keys, and ``transaction_utility``.
    """
    _validate_config(max_transaction_len, window_granularity, utility_mode)
    _validate_required_columns(df)

    data = df.copy()
    data.columns = [str(column).strip() for column in data.columns]

    report: dict = {
        "input_rows": int(len(data)),
        "input_columns": int(len(data.columns)),
        "max_transaction_len": max_transaction_len,
        "window_granularity": window_granularity,
        "utility_mode": utility_mode,
    }

    before = len(data)
    data = data.dropna(subset=REQUIRED_COLUMNS).copy()
    report["rows_dropped_missing_required"] = int(before - len(data))

    data["InvoiceNo"] = (
        data["InvoiceNo"].astype("string").str.strip().str.replace(r"\.0$", "", regex=True)
    )
    data["StockCode"] = data["StockCode"].astype("string").str.strip()

    before = len(data)
    data = data[~data["InvoiceNo"].str.startswith("C", na=False)].copy()
    report["rows_dropped_cancelled_invoice"] = int(before - len(data))

    data["Quantity"] = pd.to_numeric(data["Quantity"], errors="coerce")
    data["UnitPrice"] = pd.to_numeric(data["UnitPrice"], errors="coerce")

    before = len(data)
    data = data[(data["Quantity"] > 0) & (data["UnitPrice"] > 0)].copy()
    report["rows_dropped_nonpositive_quantity_or_price"] = int(before - len(data))

    data["InvoiceDate"] = pd.to_datetime(data["InvoiceDate"], errors="coerce", dayfirst=True)
    before = len(data)
    data = data.dropna(subset=["InvoiceDate"]).copy()
    report["rows_dropped_invalid_invoice_date"] = int(before - len(data))

    data["WindowKey"] = data["InvoiceDate"].dt.to_period(window_granularity).astype(str)
    raw_utility = data["Quantity"] * data["UnitPrice"]
    data["UtilityInt"] = raw_utility.round().astype("Int64").astype(int)

    before = len(data)
    data = data[data["UtilityInt"] > 0].copy()
    report["rows_dropped_nonpositive_utility"] = int(before - len(data))
    report["clean_rows"] = int(len(data))

    item_mapping, stock_to_item = _build_item_mapping(data)
    data["ItemID"] = data["StockCode"].map(stock_to_item).astype(int)

    item_level = (
        data.groupby(["InvoiceNo", "WindowKey", "ItemID"], as_index=False)
        .agg(UtilityInt=("UtilityInt", "sum"))
        .sort_values(["WindowKey", "InvoiceNo", "ItemID"])
    )

    transactions = _build_transactions(item_level)
    tx_before_filter = _transactions_to_df(transactions)
    tx_after_filter = _apply_max_len_filter(tx_before_filter, max_transaction_len)

    temporal_db = _build_temporal_db(
        tx_after_filter,
        metadata={
            "source_rows": report["input_rows"],
            "clean_rows": report["clean_rows"],
            "max_transaction_len": max_transaction_len,
            "window_granularity": window_granularity,
            "utility_mode": utility_mode,
            "num_items": len(item_mapping),
            "num_transactions_before_filter": int(len(tx_before_filter)),
            "num_transactions_after_filter": int(len(tx_after_filter)),
            "utility_before_filter": int(tx_before_filter["transaction_utility"].sum())
            if not tx_before_filter.empty
            else 0,
            "utility_after_filter": int(tx_after_filter["transaction_utility"].sum())
            if not tx_after_filter.empty
            else 0,
        },
    )

    report.update(
        {
            "num_items": len(item_mapping),
            "transactions_before_filter": int(len(tx_before_filter)),
            "transactions_after_filter": int(len(tx_after_filter)),
            "transactions_removed_by_max_len": int(len(tx_before_filter) - len(tx_after_filter)),
            "utility_before_filter": int(tx_before_filter["transaction_utility"].sum())
            if not tx_before_filter.empty
            else 0,
            "utility_after_filter": int(tx_after_filter["transaction_utility"].sum())
            if not tx_after_filter.empty
            else 0,
            "avg_len_after": float(tx_after_filter["length"].mean())
            if not tx_after_filter.empty
            else 0.0,
            "max_len_after": int(tx_after_filter["length"].max())
            if not tx_after_filter.empty
            else 0,
            "num_windows": len(temporal_db["windows"]),
        }
    )

    return temporal_db, item_mapping, report, tx_before_filter, tx_after_filter


def compute_max_len_impact(
    transaction_df: pd.DataFrame,
    thresholds: list[int] | None = None,
) -> pd.DataFrame:
    """Compute transaction/utility retained and removed for max-length thresholds."""
    if thresholds is None:
        thresholds = [30, 40, 50, 60, 80, 100, 150, 200]

    required = {"length", "transaction_utility"}
    if transaction_df.empty:
        return pd.DataFrame(
            columns=[
                "max_len",
                "kept_tx",
                "removed_tx",
                "removed_tx_rate",
                "kept_utility",
                "removed_utility",
                "removed_utility_rate",
                "avg_len_after",
                "max_len_after",
            ]
        )
    missing = required - set(transaction_df.columns)
    if missing:
        raise ValueError(f"transaction_df missing required columns: {sorted(missing)}")

    total_tx = len(transaction_df)
    total_utility = float(transaction_df["transaction_utility"].sum())
    rows = []
    for threshold in thresholds:
        kept = transaction_df[transaction_df["length"] <= threshold]
        removed = transaction_df[transaction_df["length"] > threshold]
        kept_utility = float(kept["transaction_utility"].sum())
        removed_utility = float(removed["transaction_utility"].sum())
        rows.append(
            {
                "max_len": int(threshold),
                "kept_tx": int(len(kept)),
                "removed_tx": int(len(removed)),
                "removed_tx_rate": float(len(removed) / total_tx) if total_tx else 0.0,
                "kept_utility": int(round(kept_utility)),
                "removed_utility": int(round(removed_utility)),
                "removed_utility_rate": float(removed_utility / total_utility)
                if total_utility
                else 0.0,
                "avg_len_after": float(kept["length"].mean()) if not kept.empty else 0.0,
                "max_len_after": int(kept["length"].max()) if not kept.empty else 0,
            }
        )

    return pd.DataFrame(rows)


def save_preprocessing_outputs(
    temporal_db: dict,
    item_mapping: dict,
    output_dir: str | Path = "app_outputs",
) -> dict[str, Path]:
    """Write preprocessing JSON artifacts and return their paths."""
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    temporal_db_path = output_path / "temporal_db.json"
    item_mapping_path = output_path / "item_mapping.json"

    temporal_db_path.write_text(
        json.dumps(temporal_db, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    item_mapping_path.write_text(
        json.dumps(item_mapping, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    return {
        "temporal_db": temporal_db_path,
        "item_mapping": item_mapping_path,
    }


def build_temporal_database(
    df: pd.DataFrame,
    config: PreprocessConfig,
) -> dict:
    """Build only the temporal DB payload from raw retail rows."""
    temporal_db, _, _, _, _ = preprocess_retail_df(
        df,
        max_transaction_len=config.max_transaction_len,
        window_granularity=config.window_granularity,
        utility_mode=config.utility_mode,
    )
    return temporal_db


def _validate_config(
    max_transaction_len: Optional[int],
    window_granularity: str,
    utility_mode: str,
) -> None:
    """Validate preprocessing configuration."""
    if max_transaction_len is not None and max_transaction_len < 1:
        raise ValueError("max_transaction_len must be None or a positive integer.")
    if window_granularity != "M":
        raise ValueError("Only monthly window_granularity='M' is supported for now.")
    if utility_mode != "round":
        raise ValueError("Only utility_mode='round' is supported for now.")


def _validate_required_columns(df: pd.DataFrame) -> None:
    """Raise ValueError when required source columns are absent."""
    normalized_columns = {str(column).strip() for column in df.columns}
    missing = [column for column in REQUIRED_COLUMNS if column not in normalized_columns]
    if missing:
        raise ValueError(f"Missing required columns: {', '.join(missing)}")


def _build_item_mapping(data: pd.DataFrame) -> tuple[dict, dict[str, int]]:
    """Build StockCode to ItemID mapping and JSON-ready item metadata."""
    stock_codes = sorted(data["StockCode"].dropna().astype(str).unique().tolist())
    stock_to_item = {stock_code: index + 1 for index, stock_code in enumerate(stock_codes)}

    descriptions: dict[str, str | None] = {}
    if "Description" in data.columns:
        desc_frame = data[["StockCode", "Description"]].copy()
        desc_frame["Description"] = desc_frame["Description"].astype("string")
        for stock_code, group in desc_frame.groupby("StockCode", dropna=False):
            non_empty = group["Description"].dropna()
            descriptions[str(stock_code)] = str(non_empty.iloc[0]) if not non_empty.empty else None

    item_mapping: dict[str, dict] = {}
    for stock_code, item_id in stock_to_item.items():
        item_mapping[str(item_id)] = {
            "ItemID": item_id,
            "StockCode": stock_code,
            "Description": descriptions.get(stock_code),
        }

    return item_mapping, stock_to_item


def _build_transactions(item_level: pd.DataFrame) -> list[dict]:
    """Build transaction dictionaries from deduplicated item-level rows."""
    transactions: list[dict] = []
    grouped = item_level.groupby(["WindowKey", "InvoiceNo"], sort=True)
    for (window_key, invoice_no), group in grouped:
        group = group.sort_values("ItemID")
        items = [int(item_id) for item_id in group["ItemID"].tolist()]
        item_utils = {
            str(int(row.ItemID)): int(row.UtilityInt)
            for row in group.itertuples(index=False)
        }
        transaction_utility = int(sum(item_utils.values()))
        invoice_text = str(invoice_no)
        window_text = str(window_key)
        transactions.append(
            {
                "tid": f"{window_text}_{invoice_text}",
                "invoice_no": invoice_text,
                "window": window_text,
                "items": items,
                "item_utils": item_utils,
                "transaction_utility": transaction_utility,
                "length": len(items),
            }
        )
    return transactions


def _transactions_to_df(transactions: list[dict]) -> pd.DataFrame:
    """Convert transaction dictionaries to a display/filter DataFrame."""
    columns = [
        "tid",
        "invoice_no",
        "window",
        "items",
        "item_utils",
        "transaction_utility",
        "length",
    ]
    return pd.DataFrame(transactions, columns=columns)


def _apply_max_len_filter(
    tx_before_filter: pd.DataFrame,
    max_transaction_len: Optional[int],
) -> pd.DataFrame:
    """Filter transaction DataFrame by max item length when requested."""
    if tx_before_filter.empty:
        return tx_before_filter.copy()
    if max_transaction_len is None:
        return tx_before_filter.copy()
    return tx_before_filter[tx_before_filter["length"] <= max_transaction_len].copy()


def _build_temporal_db(tx_after_filter: pd.DataFrame, metadata: dict) -> dict:
    """Build the temporal DB JSON payload from filtered transactions."""
    windows: dict[str, dict] = {}
    if not tx_after_filter.empty:
        for window_key, group in tx_after_filter.groupby("window", sort=True):
            transactions = []
            for tx in group.sort_values("tid").to_dict(orient="records"):
                transactions.append(
                    {
                        "tid": str(tx["tid"]),
                        "invoice_no": str(tx["invoice_no"]),
                        "window": str(tx["window"]),
                        "items": [int(item) for item in tx["items"]],
                        "item_utils": {
                            str(item_id): int(utility)
                            for item_id, utility in tx["item_utils"].items()
                        },
                        "transaction_utility": int(tx["transaction_utility"]),
                    }
                )
            windows[str(window_key)] = {
                "window_key": str(window_key),
                "total_utility": int(group["transaction_utility"].sum()),
                "num_transactions": int(len(group)),
                "transactions": transactions,
            }

    return {
        "metadata": metadata,
        "windows": windows,
    }
