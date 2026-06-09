"""Phase 3 independent verification for the TA-PPHUIM pipeline.

This module recomputes utility metrics from the original and sanitized temporal
databases. It does not mutate or sanitize data.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd

from modules.mapping_utils import normalize_item_mapping


def audit_temporal_db(db: dict) -> dict:
    """Audit a temporal DB for transaction utility and item integrity issues.

    Returns a dict with count fields required by the Phase 3 report plus compact
    detail rows that can be inspected in JSON output.
    """
    result = {
        "bad_tu": 0,
        "empty_transactions": 0,
        "duplicate_items": 0,
        "zero_or_negative_item_utils": 0,
        "details": {
            "bad_tu": [],
            "empty_transactions": [],
            "duplicate_items": [],
            "zero_or_negative_item_utils": [],
        },
    }

    for window_key, tx in _iter_transactions(db):
        tid = str(tx.get("tid", ""))
        item_utils = _item_utils(tx)
        items = _items(tx, item_utils)
        positive_items = [item for item in items if item_utils.get(str(item), 0) > 0]
        declared_tu = _transaction_utility(tx, item_utils)
        computed_tu = int(sum(item_utils.values()))

        if declared_tu != computed_tu:
            result["bad_tu"] += 1
            result["details"]["bad_tu"].append(
                {
                    "window": str(window_key),
                    "tid": tid,
                    "declared_tu": declared_tu,
                    "computed_tu": computed_tu,
                }
            )

        if not positive_items or declared_tu <= 0:
            result["empty_transactions"] += 1
            result["details"]["empty_transactions"].append(
                {"window": str(window_key), "tid": tid, "transaction_utility": declared_tu}
            )

        if len(items) != len(set(items)):
            result["duplicate_items"] += 1
            result["details"]["duplicate_items"].append(
                {"window": str(window_key), "tid": tid, "items": items}
            )

        for item, utility in item_utils.items():
            if int(utility) <= 0:
                result["zero_or_negative_item_utils"] += 1
                result["details"]["zero_or_negative_item_utils"].append(
                    {
                        "window": str(window_key),
                        "tid": tid,
                        "item_id": int(item),
                        "utility": int(utility),
                    }
                )

    return result


def compute_total_utility(db: dict) -> int:
    """Compute total utility directly from transactions."""
    total = 0
    for _, tx in _iter_transactions(db):
        item_utils = _item_utils(tx)
        total += _transaction_utility(tx, item_utils)
    return int(total)


def collect_sensitive_patterns_from_phase1(phase1_output: dict) -> dict:
    """Collect Phase 1 selected sensitive patterns keyed by pattern key."""
    selected = list(phase1_output.get("selected_shuis", []))
    if not selected:
        for window_payload in phase1_output.get("windows", {}).values():
            selected.extend(window_payload.get("selected_shuis", []))

    sensitive_patterns: dict[str, dict] = {}
    for pattern in selected:
        items = tuple(sorted(int(item) for item in pattern.get("items", [])))
        if not items:
            continue
        key = pattern.get("pattern_key") or _pattern_key(items)
        payload = sensitive_patterns.setdefault(
            key,
            {
                "pattern_key": key,
                "items": items,
                "local_target_windows": set(),
                "peak_windows": set(),
            },
        )
        selected_window = pattern.get("selected_window")
        if selected_window:
            payload["local_target_windows"].add(str(selected_window))
        for window in pattern.get("peak_windows", []) or []:
            payload["peak_windows"].add(str(window))
        if pattern.get("max_window"):
            payload["peak_windows"].add(str(pattern["max_window"]))
    return sensitive_patterns


def recompute_sensitive_pattern_utils(
    db: dict,
    sensitive_patterns: dict,
) -> dict:
    """Recompute sensitive pattern utility by window and globally."""
    window_keys = sorted(str(key) for key in db.get("windows", {}))
    results = {}
    for pattern_key, payload in sensitive_patterns.items():
        items = tuple(int(item) for item in payload.get("items", []))
        by_window = {window: 0 for window in window_keys}
        for window_key, tx in _iter_transactions(db):
            by_window[str(window_key)] += _pattern_utility_in_tx(tx, items)
        results[pattern_key] = {
            "pattern_key": pattern_key,
            "items": list(items),
            "by_window": by_window,
            "global": int(sum(by_window.values())),
        }
    return results


def verify_local_hiding(
    phase1_output: dict,
    original_db: dict,
    sanitized_db: dict,
    local_ratio: float,
) -> pd.DataFrame:
    """Verify local hiding per temporal window."""
    sensitive_patterns = collect_sensitive_patterns_from_phase1(phase1_output)
    sanitized_utils = recompute_sensitive_pattern_utils(sanitized_db, sensitive_patterns)
    rows = []

    all_windows = sorted(
        set(str(key) for key in original_db.get("windows", {}))
        | set(str(key) for key in sanitized_db.get("windows", {}))
    )
    for window_key in all_windows:
        original_utility = _window_total_utility(original_db, window_key)
        sanitized_utility = _window_total_utility(sanitized_db, window_key)
        threshold = _threshold_abs(original_utility, float(local_ratio))
        target_keys = [
            key
            for key, payload in sensitive_patterns.items()
            if window_key in payload.get("local_target_windows", set())
        ]
        violations = [
            key
            for key in target_keys
            if int(sanitized_utils.get(key, {}).get("by_window", {}).get(window_key, 0))
            >= threshold
        ]
        hidden = len(target_keys) - len(violations)
        utility_loss_rate = (
            (original_utility - sanitized_utility) / original_utility
            if original_utility
            else 0.0
        )
        rows.append(
            {
                "window": window_key,
                "targets": len(target_keys),
                "hidden": hidden,
                "violations": len(violations),
                "violation_pattern_keys": " ".join(violations),
                "local_threshold_abs": int(threshold),
                "original_utility": int(original_utility),
                "sanitized_utility": int(sanitized_utility),
                "utility_reduced": int(original_utility - sanitized_utility),
                "utility_loss_rate": float(utility_loss_rate),
            }
        )

    return pd.DataFrame(rows)


def verify_global_leakage(
    sensitive_patterns: dict,
    sanitized_pattern_utils: dict,
    global_threshold_abs: int,
) -> list[str]:
    """Return sensitive pattern keys still leaking globally."""
    leaking = []
    for pattern_key in sensitive_patterns:
        utility = int(sanitized_pattern_utils.get(pattern_key, {}).get("global", 0))
        if utility >= int(global_threshold_abs):
            leaking.append(pattern_key)
    return leaking


def compare_modified_transactions(
    original_db: dict,
    sanitized_db: dict,
    item_mapping: dict | None = None,
) -> pd.DataFrame:
    """Return item-level before/after utility changes."""
    normalized_mapping = normalize_item_mapping(item_mapping)
    original_lookup = _transaction_lookup(original_db)
    sanitized_lookup = _transaction_lookup(sanitized_db)
    rows = []

    for key in sorted(set(original_lookup) | set(sanitized_lookup)):
        original_tx = original_lookup.get(key, {})
        sanitized_tx = sanitized_lookup.get(key, {})
        window, tid = key
        original_utils = _item_utils(original_tx)
        sanitized_utils = _item_utils(sanitized_tx)
        item_ids = sorted(set(map(int, original_utils)) | set(map(int, sanitized_utils)))
        for item_id in item_ids:
            before = int(original_utils.get(str(item_id), 0))
            after = int(sanitized_utils.get(str(item_id), 0))
            delta = before - after
            if delta == 0:
                continue
            mapping = normalized_mapping.get(item_id, {})
            rows.append(
                {
                    "window": str(window),
                    "tid": str(tid),
                    "invoice_no": str(
                        sanitized_tx.get("invoice_no")
                        or original_tx.get("invoice_no")
                        or ""
                    ),
                    "item_id": int(item_id),
                    "stock_code": mapping.get("stock_code", str(item_id)),
                    "description": mapping.get("description", ""),
                    "before_utility": before,
                    "after_utility": after,
                    "delta": int(delta),
                }
            )

    return pd.DataFrame(
        rows,
        columns=[
            "window",
            "tid",
            "invoice_no",
            "item_id",
            "stock_code",
            "description",
            "before_utility",
            "after_utility",
            "delta",
        ],
    )


def phase3_verify(
    phase1_output: dict,
    original_db: dict,
    phase2_output: dict,
    item_mapping: dict | None = None,
    local_ratio: float = 0.015,
    global_ratio: float = 0.015,
    output_dir: str | Path = "app_outputs",
) -> tuple[dict, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Run Phase 3 verification and save JSON/CSV outputs."""
    sanitized_db = _extract_sanitized_db(phase2_output)
    sensitive_patterns = collect_sensitive_patterns_from_phase1(phase1_output)

    original_total_utility = compute_total_utility(original_db)
    sanitized_total_utility = compute_total_utility(sanitized_db)
    total_utility_reduced = int(original_total_utility - sanitized_total_utility)
    utility_loss_rate = (
        total_utility_reduced / original_total_utility if original_total_utility else 0.0
    )

    integrity_audit = audit_temporal_db(sanitized_db)
    window_metrics_df = verify_local_hiding(
        phase1_output,
        original_db,
        sanitized_db,
        local_ratio,
    )
    original_pattern_utils = recompute_sensitive_pattern_utils(
        original_db,
        sensitive_patterns,
    )
    sanitized_pattern_utils = recompute_sensitive_pattern_utils(
        sanitized_db,
        sensitive_patterns,
    )
    global_threshold_abs = _threshold_abs(original_total_utility, float(global_ratio))
    global_leaks = verify_global_leakage(
        sensitive_patterns,
        sanitized_pattern_utils,
        global_threshold_abs,
    )
    pattern_metrics_df = _build_pattern_metrics_df(
        sensitive_patterns,
        original_pattern_utils,
        sanitized_pattern_utils,
        global_threshold_abs,
        global_leaks,
    )
    modified_transactions_df = compare_modified_transactions(
        original_db,
        sanitized_db,
        item_mapping,
    )

    local_violations_after = (
        int(window_metrics_df["violations"].sum()) if not window_metrics_df.empty else 0
    )
    modified_transactions = (
        int(modified_transactions_df["tid"].nunique())
        if not modified_transactions_df.empty
        else 0
    )
    total_transactions = _transaction_count(original_db)
    modified_tx_rate = modified_transactions / total_transactions if total_transactions else 0.0

    pass_integrity = all(
        int(integrity_audit.get(key, 0)) == 0
        for key in [
            "bad_tu",
            "empty_transactions",
            "duplicate_items",
            "zero_or_negative_item_utils",
        ]
    )
    pass_local = local_violations_after == 0
    pass_global = len(global_leaks) == 0

    report = {
        "original_total_utility": int(original_total_utility),
        "sanitized_total_utility": int(sanitized_total_utility),
        "total_utility_reduced": int(total_utility_reduced),
        "utility_loss_rate": float(utility_loss_rate),
        "local_violations_after": int(local_violations_after),
        "global_leaks_after": len(global_leaks),
        "global_leaking_pattern_keys": global_leaks,
        "modified_transactions": int(modified_transactions),
        "modified_tx_rate": float(modified_tx_rate),
        "pass_integrity": bool(pass_integrity),
        "pass_local": bool(pass_local),
        "pass_global": bool(pass_global),
        "PHASE3_PASS": bool(pass_integrity and pass_local and pass_global),
        "local_ratio": float(local_ratio),
        "global_ratio": float(global_ratio),
        "global_threshold_abs": int(global_threshold_abs),
        "total_transactions": int(total_transactions),
        "integrity_audit": integrity_audit,
    }

    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    _write_json(output_path / "phase3_verification_report.json", report)
    window_metrics_df.to_csv(output_path / "phase3_window_metrics.csv", index=False)
    pattern_metrics_df.to_csv(output_path / "phase3_pattern_metrics.csv", index=False)

    return report, window_metrics_df, pattern_metrics_df, modified_transactions_df


def _build_pattern_metrics_df(
    sensitive_patterns: dict,
    original_pattern_utils: dict,
    sanitized_pattern_utils: dict,
    global_threshold_abs: int,
    global_leaks: list[str],
) -> pd.DataFrame:
    """Build one row per sensitive pattern."""
    rows = []
    leaking_keys = set(global_leaks)
    for pattern_key, payload in sorted(sensitive_patterns.items()):
        original_payload = original_pattern_utils.get(pattern_key, {})
        sanitized_payload = sanitized_pattern_utils.get(pattern_key, {})
        sanitized_global = int(sanitized_payload.get("global", 0))
        rows.append(
            {
                "pattern_key": pattern_key,
                "items": " ".join(str(item) for item in payload.get("items", [])),
                "local_target_windows": " ".join(
                    sorted(payload.get("local_target_windows", set()))
                ),
                "peak_windows": " ".join(sorted(payload.get("peak_windows", set()))),
                "original_global_utility": int(original_payload.get("global", 0)),
                "sanitized_global_utility": sanitized_global,
                "global_threshold_abs": int(global_threshold_abs),
                "global_leak": pattern_key in leaking_keys,
            }
        )
    return pd.DataFrame(rows)


def _extract_sanitized_db(phase2_output: dict) -> dict:
    """Extract sanitized DB from the Phase 2 output schema."""
    sanitized_db = phase2_output.get("sanitized_db")
    if sanitized_db is None and "windows" in phase2_output:
        sanitized_db = phase2_output
    if not isinstance(sanitized_db, dict) or "windows" not in sanitized_db:
        raise ValueError("phase2_output does not contain a sanitized_db with windows.")
    return sanitized_db


def _iter_transactions(db: dict):
    """Yield (window_key, transaction) pairs from a temporal DB."""
    for window_key, window_payload in db.get("windows", {}).items():
        for tx in window_payload.get("transactions", []):
            yield str(window_key), tx


def _transaction_lookup(db: dict) -> dict[tuple[str, str], dict]:
    """Build a lookup keyed by (window, tid)."""
    lookup = {}
    for window_key, tx in _iter_transactions(db):
        lookup[(str(window_key), str(tx.get("tid", "")))] = tx
    return lookup


def _transaction_count(db: dict) -> int:
    """Count transactions in a temporal DB."""
    return sum(1 for _ in _iter_transactions(db))


def _window_total_utility(db: dict, window_key: str) -> int:
    """Compute one window's total utility directly from transactions."""
    window = db.get("windows", {}).get(str(window_key), {})
    total = 0
    for tx in window.get("transactions", []):
        item_utils = _item_utils(tx)
        total += _transaction_utility(tx, item_utils)
    return int(total)


def _pattern_utility_in_tx(tx: dict, pattern_items: tuple[int, ...]) -> int:
    """Compute pattern utility in a transaction when all items are present."""
    item_utils = _item_utils(tx)
    total = 0
    for item in pattern_items:
        utility = int(item_utils.get(str(int(item)), 0))
        if utility <= 0:
            return 0
        total += utility
    return int(total)


def _items(tx: dict, item_utils: dict[str, int]) -> list[int]:
    """Return transaction items as ints."""
    raw_items = tx.get("items", [])
    if raw_items:
        return [int(item) for item in raw_items]
    return sorted(int(item) for item in item_utils)


def _item_utils(tx: dict) -> dict[str, int]:
    """Return item utilities with string keys and int values."""
    item_utils = {}
    for item, utility in tx.get("item_utils", {}).items():
        try:
            item_utils[str(int(item))] = int(utility)
        except (TypeError, ValueError):
            continue
    return item_utils


def _transaction_utility(tx: dict, item_utils: dict[str, int]) -> int:
    """Return declared transaction utility with computed fallback."""
    try:
        return int(tx.get("transaction_utility", tx.get("tu", sum(item_utils.values()))))
    except (TypeError, ValueError):
        return int(sum(item_utils.values()))


def _threshold_abs(total_utility: int, ratio: float) -> int:
    """Compute positive absolute utility threshold when utility exists."""
    if total_utility <= 0:
        return 0
    return max(1, int(total_utility * ratio))


def _pattern_key(items: tuple[int, ...]) -> str:
    """Return a canonical itemset key."""
    return " ".join(str(int(item)) for item in sorted(items))


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    """Write a JSON file with UTF-8 encoding."""
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
