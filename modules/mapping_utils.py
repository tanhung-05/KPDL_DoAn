"""Display helpers for mapping integer ItemID values back to product labels."""

from __future__ import annotations

from typing import Any


def normalize_item_mapping(item_mapping: dict | None) -> dict[int, dict[str, str]]:
    """Normalize supported item mapping formats to ``int ItemID`` keys.

    Supports ``item_id -> stock_code``, ``stock_code -> item_id``, and dict
    payloads containing ``StockCode``/``Description``.
    """
    if not item_mapping:
        return {}

    normalized: dict[int, dict[str, str]] = {}
    for raw_key, raw_value in item_mapping.items():
        parsed = _parse_mapping_entry(raw_key, raw_value)
        if parsed is None:
            continue
        item_id, stock_code, description = parsed
        normalized[item_id] = {
            "stock_code": stock_code,
            "description": description,
        }
    return normalized


def item_id_to_label(item_id: int, item_mapping: dict | None) -> str:
    """Return ``ItemID ... | StockCode ...`` with description when available."""
    item_id_int = int(item_id)
    normalized = normalize_item_mapping(item_mapping)
    payload = normalized.get(item_id_int)
    if not payload:
        return f"ItemID {item_id_int}"

    label = f"ItemID {item_id_int} | StockCode {payload['stock_code']}"
    if payload.get("description"):
        label += f" | Description {payload['description']}"
    return label


def pattern_to_labels(items: list[int], item_mapping: dict | None) -> list[str]:
    """Return display labels for every item in a pattern."""
    return [item_id_to_label(int(item), item_mapping) for item in items]


def pattern_to_short_text(
    items: list[int],
    item_mapping: dict | None,
    max_items: int = 5,
) -> str:
    """Return a compact StockCode/Description summary for table cells."""
    normalized = normalize_item_mapping(item_mapping)
    labels = []
    for item in [int(item) for item in items[:max_items]]:
        payload = normalized.get(item)
        if payload:
            stock_code = payload["stock_code"]
            description = payload.get("description", "")
            labels.append(f"{stock_code} - {description}" if description else stock_code)
        else:
            labels.append(f"ItemID {item}")

    remaining = max(0, len(items) - max_items)
    if remaining:
        labels.append(f"+{remaining} more")
    return " | ".join(labels)


def _parse_mapping_entry(raw_key: Any, raw_value: Any) -> tuple[int, str, str] | None:
    """Parse one mapping entry into item ID, stock code, and description."""
    if isinstance(raw_value, dict):
        item_id_value = raw_value.get("ItemID") or raw_value.get("item_id")
        if item_id_value is None and _is_int_like(raw_key):
            item_id_value = raw_key
        if item_id_value is None:
            item_id_value = raw_value.get("id")
        if item_id_value is None:
            return None

        item_id = int(item_id_value)
        stock_code = (
            raw_value.get("StockCode")
            or raw_value.get("stock_code")
            or raw_value.get("stockCode")
            or raw_key
        )
        description = raw_value.get("Description") or raw_value.get("description") or ""
        return item_id, str(stock_code), "" if description is None else str(description)

    if _is_int_like(raw_key):
        return int(raw_key), str(raw_value), ""

    if _is_int_like(raw_value):
        return int(raw_value), str(raw_key), ""

    return None


def _is_int_like(value: Any) -> bool:
    """Return True when a value can be parsed as an integer ID."""
    try:
        int(value)
    except (TypeError, ValueError):
        return False
    return True

