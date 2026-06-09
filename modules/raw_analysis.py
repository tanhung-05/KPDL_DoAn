"""Raw retail CSV profiling utilities.

These functions analyze uploaded data before preprocessing. They copy input
DataFrames before deriving numeric/date fields and never mutate caller data.
"""

from __future__ import annotations

import pandas as pd

from modules.constants import REQUIRED_COLUMNS


def validate_required_columns(df: pd.DataFrame) -> list[str]:
    """Return required columns that are missing from the uploaded data."""
    return [column for column in REQUIRED_COLUMNS if column not in df.columns]


def compute_raw_summary(df: pd.DataFrame) -> dict:
    """Compute high-level quality and utility metrics for raw uploaded data.

    Returns a dictionary with total rows/columns, invoice/item counts, missing
    required values, cancelled invoices, invalid numeric rows, date range, and
    raw utility computed as ``Quantity * UnitPrice`` with coercion.
    """
    data = df.copy()
    quantity = _numeric_series(data, "Quantity")
    unit_price = _numeric_series(data, "UnitPrice")
    invoice_dates = _datetime_series(data, "InvoiceDate")
    data["QuantityNum"] = quantity
    data["UnitPriceNum"] = unit_price
    data["RawUtility"] = (quantity * unit_price).fillna(0)
    data["InvoiceDateParsed"] = invoice_dates

    required_present = [column for column in REQUIRED_COLUMNS if column in data.columns]
    if required_present:
        missing_required_rows = int(data[required_present].isna().any(axis=1).sum())
    else:
        missing_required_rows = int(len(data))

    invoice_no = _string_series(data, "InvoiceNo")
    stock_code = _string_series(data, "StockCode")
    valid_dates = invoice_dates.dropna()

    invalid_quantity_rows = int(
        ((quantity.isna() & data.get("Quantity", pd.Series(index=data.index)).notna()) | (quantity <= 0)).sum()
    )
    invalid_unitprice_rows = int(
        ((unit_price.isna() & data.get("UnitPrice", pd.Series(index=data.index)).notna()) | (unit_price <= 0)).sum()
    )

    valid_mask = _valid_sales_mask(data)
    clean_data = data[valid_mask].copy()
    clean_utility = clean_data["RawUtility"] if "RawUtility" in clean_data.columns else (quantity * unit_price).fillna(0)[valid_mask]
    clean_invoice_no = clean_data["InvoiceNo"].astype("string") if "InvoiceNo" in clean_data.columns else pd.Series(dtype="string")
    total_revenue = float(clean_utility.sum())
    invoice_count = int(clean_invoice_no.nunique(dropna=True))

    return {
        "total_rows": int(len(data)),
        "total_columns": int(len(data.columns)),
        "total_invoices": int(invoice_no.nunique(dropna=True)),
        "total_items": int(stock_code.nunique(dropna=True)),
        "total_revenue": total_revenue,
        "valid_transactions": int(len(clean_data)),
        "valid_invoices": invoice_count,
        "removed_rows": int(len(data) - len(clean_data)),
        "average_invoice_value": float(total_revenue / invoice_count) if invoice_count else 0.0,
        "data_months": int(clean_data["InvoiceDateParsed"].dt.to_period("M").nunique()) if not clean_data.empty else 0,
        "missing_required_rows": missing_required_rows,
        "cancelled_invoices_count": int(invoice_no.str.startswith("C", na=False).sum()),
        "invalid_quantity_rows": invalid_quantity_rows,
        "invalid_unitprice_rows": invalid_unitprice_rows,
        "date_min": _format_date(valid_dates.min()) if not valid_dates.empty else None,
        "date_max": _format_date(valid_dates.max()) if not valid_dates.empty else None,
        "raw_total_utility": float((quantity * unit_price).fillna(0).sum()),
    }


def validate_sales_csv_columns(df: pd.DataFrame) -> dict:
    """Return user-friendly validation details for uploaded sales CSV columns."""
    missing = validate_required_columns(df)
    display_names = {
        "InvoiceNo": "Mã hóa đơn",
        "StockCode": "Mã sản phẩm",
        "Quantity": "Số lượng",
        "UnitPrice": "Đơn giá",
        "InvoiceDate": "Ngày bán",
    }
    return {
        "is_valid": not missing,
        "required_columns": list(REQUIRED_COLUMNS),
        "missing_columns": missing,
        "friendly_columns": [
            {"label": display_names.get(column, column), "column": column}
            for column in REQUIRED_COLUMNS
        ],
    }


def clean_sales_data(df: pd.DataFrame) -> pd.DataFrame:
    """Return rows usable for business-facing sales analytics."""
    data = _base_raw_frame(df)
    return data[_valid_sales_mask(data)].copy()


def compute_sales_overview(clean_df: pd.DataFrame) -> dict:
    """Compute business-facing metrics from cleaned sales data."""
    if clean_df.empty:
        return {
            "total_revenue": 0.0,
            "invoice_count": 0,
            "product_count": 0,
            "data_months": 0,
            "average_invoice_value": 0.0,
            "valid_transactions": 0,
        }

    invoice_count = int(clean_df["InvoiceNo"].astype("string").nunique(dropna=True))
    total_revenue = float(clean_df["RawUtility"].sum())
    return {
        "total_revenue": total_revenue,
        "invoice_count": invoice_count,
        "product_count": int(clean_df["StockCode"].astype("string").nunique(dropna=True)),
        "data_months": int(clean_df["InvoiceDateParsed"].dt.to_period("M").nunique()),
        "average_invoice_value": float(total_revenue / invoice_count) if invoice_count else 0.0,
        "valid_transactions": int(len(clean_df)),
    }


def build_raw_monthly_stats(df: pd.DataFrame) -> pd.DataFrame:
    """Build raw monthly stats with rows, invoices, quantity, and utility.

    Output columns: ``WindowKey``, ``rows``, ``invoices``, ``total_quantity``,
    ``total_utility``. Rows with unparseable ``InvoiceDate`` are excluded.
    """
    data = clean_sales_data(df)
    if data.empty:
        return pd.DataFrame(
            columns=["WindowKey", "rows", "invoices", "total_quantity", "total_utility"]
        )

    data["WindowKey"] = data["InvoiceDateParsed"].dt.to_period("M").astype(str)
    monthly = (
        data.groupby("WindowKey", as_index=False)
        .agg(
            rows=("InvoiceNo", "size"),
            invoices=("InvoiceNo", "nunique"),
            total_quantity=("QuantityNum", "sum"),
            total_utility=("RawUtility", "sum"),
        )
        .sort_values("WindowKey")
    )
    return monthly


def build_top_products_by_utility(df: pd.DataFrame, top_n: int = 10) -> pd.DataFrame:
    """Return the top products by raw utility contribution."""
    data = clean_sales_data(df)
    group_columns = ["StockCode"]
    if "Description" in data.columns:
        group_columns.append("Description")

    top_products = (
        data.groupby(group_columns, dropna=False, as_index=False)
        .agg(total_quantity=("QuantityNum", "sum"), total_utility=("RawUtility", "sum"))
        .sort_values("total_utility", ascending=False)
        .head(top_n)
    )
    return top_products


def build_top_products_by_quantity(df: pd.DataFrame, top_n: int = 10) -> pd.DataFrame:
    """Return top products by sold quantity from cleaned sales rows."""
    data = clean_sales_data(df)
    if data.empty:
        return pd.DataFrame(columns=["StockCode", "Description", "total_quantity", "total_utility", "invoice_count"])
    return _product_aggregate(data).sort_values("total_quantity", ascending=False).head(top_n)


def build_product_table(df: pd.DataFrame, top_n: int = 100) -> pd.DataFrame:
    """Return a product table for the business dashboard."""
    data = clean_sales_data(df)
    if data.empty:
        return pd.DataFrame(columns=["StockCode", "Description", "total_quantity", "total_utility", "invoice_count"])
    return _product_aggregate(data).sort_values("total_utility", ascending=False).head(top_n)


def build_transaction_length_stats_raw(df: pd.DataFrame) -> pd.Series:
    """Return raw transaction lengths as distinct ``StockCode`` count per invoice."""
    if "InvoiceNo" not in df.columns or "StockCode" not in df.columns:
        return pd.Series(dtype="int64", name="transaction_length")

    data = df.copy()
    lengths = (
        data.groupby(data["InvoiceNo"].astype("string"))["StockCode"]
        .nunique(dropna=True)
        .rename("transaction_length")
    )
    return lengths


def build_transaction_utility_stats_raw(df: pd.DataFrame) -> pd.Series:
    """Return raw transaction utility as ``sum(Quantity * UnitPrice)`` per invoice."""
    if "InvoiceNo" not in df.columns:
        return pd.Series(dtype="float64", name="transaction_utility")

    data = _base_raw_frame(df)
    utilities = (
        data.groupby(data["InvoiceNo"].astype("string"))["RawUtility"]
        .sum()
        .rename("transaction_utility")
    )
    return utilities


def _base_raw_frame(df: pd.DataFrame) -> pd.DataFrame:
    """Return a copied frame with safe numeric, utility, and parsed date columns."""
    data = df.copy()
    data["QuantityNum"] = _numeric_series(data, "Quantity")
    data["UnitPriceNum"] = _numeric_series(data, "UnitPrice")
    data["RawUtility"] = (data["QuantityNum"] * data["UnitPriceNum"]).fillna(0)
    data["InvoiceDateParsed"] = _datetime_series(data, "InvoiceDate")
    return data


def _valid_sales_mask(df: pd.DataFrame) -> pd.Series:
    """Return rows with usable invoice, item, positive quantity/price, and date."""
    required_present = all(column in df.columns for column in REQUIRED_COLUMNS)
    if not required_present:
        return pd.Series(False, index=df.index)
    invoice = df["InvoiceNo"].astype("string")
    stock = df["StockCode"].astype("string")
    return (
        invoice.notna()
        & ~invoice.str.startswith("C", na=False)
        & stock.notna()
        & df["QuantityNum"].notna()
        & (df["QuantityNum"] > 0)
        & df["UnitPriceNum"].notna()
        & (df["UnitPriceNum"] > 0)
        & df["InvoiceDateParsed"].notna()
    )


def _product_aggregate(data: pd.DataFrame) -> pd.DataFrame:
    """Aggregate cleaned rows by product for dashboard tables."""
    group_columns = ["StockCode"]
    if "Description" in data.columns:
        group_columns.append("Description")
    product_table = (
        data.groupby(group_columns, dropna=False, as_index=False)
        .agg(
            total_quantity=("QuantityNum", "sum"),
            total_utility=("RawUtility", "sum"),
            invoice_count=("InvoiceNo", "nunique"),
        )
    )
    return product_table


def _numeric_series(df: pd.DataFrame, column: str) -> pd.Series:
    """Return a numeric series using coercion for missing or invalid values."""
    if column not in df.columns:
        return pd.Series(pd.NA, index=df.index, dtype="Float64")
    return pd.to_numeric(df[column], errors="coerce")


def _datetime_series(df: pd.DataFrame, column: str) -> pd.Series:
    """Return a datetime series using day-first parsing and coercion."""
    if column not in df.columns:
        return pd.Series(pd.NaT, index=df.index, dtype="datetime64[ns]")
    return pd.to_datetime(df[column], errors="coerce", dayfirst=True)


def _string_series(df: pd.DataFrame, column: str) -> pd.Series:
    """Return a string series for an optional column."""
    if column not in df.columns:
        return pd.Series(pd.NA, index=df.index, dtype="string")
    return df[column].astype("string")


def _format_date(value: pd.Timestamp) -> str | None:
    """Format a timestamp as YYYY-MM-DD or return None for missing values."""
    if pd.isna(value):
        return None
    return value.strftime("%Y-%m-%d")
