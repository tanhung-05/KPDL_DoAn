"""CSV loading and schema validation helpers for retail transaction uploads."""

from typing import Any

import pandas as pd


REQUIRED_COLUMNS = [
    "InvoiceNo",
    "StockCode",
    "Quantity",
    "UnitPrice",
    "InvoiceDate",
]

OPTIONAL_COLUMNS = [
    "Description",
    "CustomerID",
    "Country",
]


def normalize_column_names(df: pd.DataFrame) -> pd.DataFrame:
    """Return a copy of ``df`` with leading/trailing whitespace removed from column names."""
    normalized = df.copy()
    normalized.columns = [str(column).strip() for column in normalized.columns]
    return normalized


def load_csv(uploaded_file: Any) -> pd.DataFrame:
    """Load an uploaded CSV file with robust encoding and separator fallbacks.

    The loader supports file-like upload objects by seeking back to the start
    before every read attempt. It tries common encodings and both comma and
    semicolon separators. For semicolon-separated files it also supports decimal
    comma values such as ``2,55``.

    Raises ``ValueError`` with attempted formats if no parse attempt succeeds.
    """
    encodings = ["utf-8", "utf-8-sig", "unicode_escape", "latin1"]
    separators = [",", ";"]
    errors = []

    for encoding in encodings:
        for separator in separators:
            _reset_file(uploaded_file)
            read_kwargs = {
                "sep": separator,
                "encoding": encoding,
            }
            if separator == ";":
                read_kwargs["decimal"] = ","

            try:
                df = pd.read_csv(uploaded_file, **read_kwargs)
            except Exception as exc:
                errors.append(f"encoding={encoding}, sep={separator!r}: {exc}")
                continue

            if _looks_like_wrong_separator(df, separator):
                errors.append(
                    f"encoding={encoding}, sep={separator!r}: parsed as one likely wrong column"
                )
                continue

            return df

    attempted = "; ".join(errors[-8:]) if errors else "no parser attempts completed"
    raise ValueError(
        "Could not read CSV. Tried encodings utf-8, utf-8-sig, unicode_escape, "
        f"latin1 with comma and semicolon separators. Recent parser errors: {attempted}"
    )


def validate_schema(df: pd.DataFrame) -> dict:
    """Validate retail CSV columns against the TA-PPHUIM upload schema.

    Returns:
        A dict with ``is_valid``, ``missing_columns``, ``required_columns``, and
        ``optional_columns_present``.
    """
    columns = set(df.columns)
    missing_columns = [column for column in REQUIRED_COLUMNS if column not in columns]
    optional_columns_present = [
        column for column in OPTIONAL_COLUMNS if column in columns
    ]

    return {
        "is_valid": not missing_columns,
        "missing_columns": missing_columns,
        "required_columns": REQUIRED_COLUMNS.copy(),
        "optional_columns_present": optional_columns_present,
    }


def _reset_file(uploaded_file: Any) -> None:
    """Seek an uploaded file back to the beginning when supported."""
    if hasattr(uploaded_file, "seek"):
        uploaded_file.seek(0)


def _looks_like_semicolon_header(df: pd.DataFrame) -> bool:
    """Return True if comma parsing likely produced one semicolon-delimited column."""
    if len(df.columns) != 1:
        return False
    return ";" in str(df.columns[0])


def _looks_like_wrong_separator(df: pd.DataFrame, separator: str) -> bool:
    """Return True when parsing likely used the wrong delimiter."""
    if len(df.columns) != 1:
        return False

    first_column = str(df.columns[0])
    if separator == ",":
        return ";" in first_column
    if separator == ";":
        return "," in first_column and all(column not in first_column for column in REQUIRED_COLUMNS)
    return False
