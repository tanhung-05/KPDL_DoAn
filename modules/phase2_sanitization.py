"""Phase 2 temporal utility sanitization.

This module hides selected Peak-Sensitive HUIs by reducing item utilities in
copied transactions. It contains no UI code.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd

from modules.mapping_utils import normalize_item_mapping


def tx_prepare(tx: dict) -> dict:
    """Normalize one transaction for sanitization."""
    item_utils = {
        str(int(item)): int(utility)
        for item, utility in tx.get("item_utils", {}).items()
    }
    items = [int(item) for item in tx.get("items", [])]
    if not items:
        items = sorted(int(item) for item in item_utils)

    prepared = {
        "tid": str(tx.get("tid", "")),
        "invoice_no": str(tx.get("invoice_no", "")),
        "window": str(tx.get("window", "")),
        "items": items,
        "item_utils": item_utils,
        "transaction_utility": int(
            tx.get("transaction_utility", tx.get("tu", sum(item_utils.values())))
        ),
    }
    prepared["_item_set"] = {
        item for item in items if int(item_utils.get(str(item), 0)) > 0
    }
    return prepared


def serialize_tx(tx: dict) -> dict:
    """Return a clean JSON-serializable transaction."""
    positive_items = [
        int(item)
        for item in tx.get("items", [])
        if int(tx.get("item_utils", {}).get(str(item), 0)) > 0
    ]
    item_utils = {
        str(item): int(tx["item_utils"].get(str(item), 0))
        for item in positive_items
    }
    transaction_utility = int(sum(item_utils.values()))
    return {
        "tid": str(tx.get("tid", "")),
        "invoice_no": str(tx.get("invoice_no", "")),
        "window": str(tx.get("window", "")),
        "items": positive_items,
        "item_utils": item_utils,
        "transaction_utility": transaction_utility,
    }


def collect_sensitive_patterns(phase1_output: dict) -> dict:
    """Collect selected SHUIs keyed by canonical pattern key."""
    sensitive_defs: dict[str, dict] = {}
    selected = list(phase1_output.get("selected_shuis", []))
    if not selected:
        for window_payload in phase1_output.get("windows", {}).values():
            selected.extend(window_payload.get("selected_shuis", []))

    for pattern in selected:
        items = tuple(sorted(int(item) for item in pattern.get("items", [])))
        if not items:
            continue
        key = pattern.get("pattern_key") or _pattern_key(items)
        payload = sensitive_defs.setdefault(
            key,
            {
                "pattern_key": key,
                "items": items,
                "peak_windows": set(),
                "local_target_windows": set(),
            },
        )
        selected_window = pattern.get("selected_window")
        if selected_window:
            payload["local_target_windows"].add(str(selected_window))
        for window in pattern.get("peak_windows", []) or []:
            payload["peak_windows"].add(str(window))
        if pattern.get("max_window"):
            payload["peak_windows"].add(str(pattern["max_window"]))

    return sensitive_defs


def build_item_to_tids(transactions: list[dict]) -> dict[int, set[str]]:
    """Build an inverted index from item ID to transaction IDs."""
    item_to_tids: dict[int, set[str]] = {}
    for tx in transactions:
        tid = str(tx["tid"])
        for item in tx.get("items", []):
            if int(tx.get("item_utils", {}).get(str(item), 0)) <= 0:
                continue
            item_to_tids.setdefault(int(item), set()).add(tid)
    return item_to_tids


def get_tids_for_pattern(pattern_items: tuple[int, ...] | list[int], item_to_tids: dict[int, set[str]]) -> set[str]:
    """Return transaction IDs containing all pattern items."""
    item_sets = [item_to_tids.get(int(item), set()) for item in pattern_items]
    if not item_sets:
        return set()
    return set.intersection(*item_sets)


def get_pattern_utility_in_tx(tx: dict, pattern_items: tuple[int, ...] | list[int]) -> int:
    """Return pattern utility in one transaction, or zero if not fully present."""
    item_utils = tx.get("item_utils", {})
    total = 0
    for item in pattern_items:
        utility = int(item_utils.get(str(int(item)), 0))
        if utility <= 0:
            return 0
        total += utility
    return int(total)


def recompute_pattern_utility_in_window(
    tx_lookup: dict[str, dict],
    tids: set[str],
    pattern_items: tuple[int, ...] | list[int],
) -> int:
    """Recompute total pattern utility over selected transaction IDs."""
    return int(
        sum(get_pattern_utility_in_tx(tx_lookup[tid], pattern_items) for tid in tids)
    )


def init_window_state(
    window_key: str,
    window_payload: dict,
    sensitive_defs: dict,
    phase1_window: dict | None,
) -> dict:
    """Initialize mutable state for one temporal window."""
    transactions = [tx_prepare(tx) for tx in window_payload.get("transactions", [])]
    tx_lookup = {tx["tid"]: tx for tx in transactions}
    item_to_tids = build_item_to_tids(transactions)

    pattern_utils = {}
    pattern_tids = {}
    for key, definition in sensitive_defs.items():
        tids = get_tids_for_pattern(definition["items"], item_to_tids)
        pattern_tids[key] = tids
        pattern_utils[key] = recompute_pattern_utility_in_window(
            tx_lookup,
            tids,
            definition["items"],
        )

    local_targets = {
        key
        for key, definition in sensitive_defs.items()
        if str(window_key) in definition["local_target_windows"]
    }

    return {
        "window_key": str(window_key),
        "total_utility_original": int(window_payload.get("total_utility", 0)),
        "phase1_window": phase1_window or {},
        "tx_lookup": tx_lookup,
        "item_to_tids": item_to_tids,
        "pattern_tids": pattern_tids,
        "pattern_utils": pattern_utils,
        "local_targets": local_targets,
    }


def choose_victim_item(tx: dict, pattern_items: tuple[int, ...] | list[int], item_scores: dict) -> int | None:
    """Choose the lowest-score item, tie-breaking by higher current utility."""
    candidates = []
    for item in pattern_items:
        utility = int(tx.get("item_utils", {}).get(str(int(item)), 0))
        if utility <= 0:
            continue
        score = _item_score(int(item), item_scores)
        candidates.append((score, -utility, int(item)))
    if not candidates:
        return None
    return sorted(candidates)[0][2]


def score_transaction(
    tx: dict,
    pattern_items: tuple[int, ...] | list[int],
    item_scores: dict,
    related_sensitive_count: int = 1,
    global_beta: float = 0.25,
    global_gamma: float = 0.75,
) -> float:
    """Score a candidate transaction for utility reduction."""
    pattern_utility = get_pattern_utility_in_tx(tx, pattern_items)
    victim = choose_victim_item(tx, pattern_items, item_scores)
    victim_score = _item_score(victim, item_scores) if victim is not None else 0.0
    return (
        pattern_utility
        + global_beta * int(tx.get("transaction_utility", 0))
        + global_gamma * related_sensitive_count
        - victim_score
    )


def decrease_item_utility(tx: dict, item: int, delta: int) -> int:
    """Decrease item utility down to zero and update transaction utility."""
    key = str(int(item))
    current = int(tx.get("item_utils", {}).get(key, 0))
    actual_delta = max(0, min(int(delta), current))
    tx["item_utils"][key] = current - actual_delta
    tx["transaction_utility"] = int(max(0, int(tx.get("transaction_utility", 0)) - actual_delta))
    tx["_item_set"] = {
        int(item_id)
        for item_id, utility in tx.get("item_utils", {}).items()
        if int(utility) > 0
    }
    return actual_delta


def apply_local_temporal_sanitization(
    window_state: dict,
    sensitive_defs: dict,
    local_threshold_abs: int,
    item_scores: dict,
    global_beta: float = 0.25,
    global_gamma: float = 0.75,
) -> tuple[list[dict], int, list[dict]]:
    """Hide local target patterns in a window by reducing utilities."""
    modifications: list[dict] = []
    utility_reduced = 0
    max_steps = max(1, len(window_state["tx_lookup"]) * max(1, len(sensitive_defs)) * 20)
    steps = 0

    for pattern_key in sorted(window_state["local_targets"]):
        definition = sensitive_defs[pattern_key]
        while window_state["pattern_utils"].get(pattern_key, 0) >= local_threshold_abs:
            steps += 1
            if steps > max_steps:
                break
            candidate_tids = get_tids_for_pattern(definition["items"], window_state["item_to_tids"])
            tx = _best_transaction(
                window_state["tx_lookup"],
                candidate_tids,
                definition["items"],
                item_scores,
                global_beta,
                global_gamma,
            )
            if tx is None:
                break

            victim_item = choose_victim_item(tx, definition["items"], item_scores)
            if victim_item is None:
                break

            current_utility = int(window_state["pattern_utils"].get(pattern_key, 0))
            needed = current_utility - local_threshold_abs + 1
            before = int(tx["item_utils"].get(str(victim_item), 0))
            delta = decrease_item_utility(tx, victim_item, needed)
            if delta <= 0:
                break
            after = int(tx["item_utils"].get(str(victim_item), 0))
            utility_reduced += delta
            modifications.append(
                _modification_record(
                    window_state["window_key"],
                    tx,
                    victim_item,
                    before,
                    after,
                    delta,
                    "local",
                    pattern_key,
                )
            )
            _refresh_window_pattern_state(window_state, sensitive_defs)

    violations = _local_violations(window_state, sensitive_defs, local_threshold_abs)
    return modifications, int(utility_reduced), violations


def compute_global_pattern_utils(
    sanitized_windows: dict,
    sensitive_defs: dict,
) -> dict[str, int]:
    """Compute global utility for every sensitive pattern."""
    totals = {key: 0 for key in sensitive_defs}
    for window in sanitized_windows.values():
        tx_lookup = window["tx_lookup"]
        item_to_tids = window["item_to_tids"]
        for key, definition in sensitive_defs.items():
            tids = get_tids_for_pattern(definition["items"], item_to_tids)
            totals[key] += recompute_pattern_utility_in_window(tx_lookup, tids, definition["items"])
    return {key: int(value) for key, value in totals.items()}


def patch_global_leakage(
    sanitized_windows: dict,
    sensitive_defs: dict,
    global_threshold_abs: int,
    item_scores: dict,
    global_beta: float = 0.25,
    global_gamma: float = 0.75,
) -> tuple[list[dict], int, list[dict], list[dict]]:
    """Patch global leakage by further reducing item utilities."""
    pre_utils = compute_global_pattern_utils(sanitized_windows, sensitive_defs)
    pre_leaks = _global_leaks(pre_utils, global_threshold_abs)
    modifications: list[dict] = []
    utility_reduced = 0
    max_steps = max(1, sum(len(w["tx_lookup"]) for w in sanitized_windows.values()) * max(1, len(sensitive_defs)) * 20)
    steps = 0

    while True:
        current_utils = compute_global_pattern_utils(sanitized_windows, sensitive_defs)
        leaks = _global_leaks(current_utils, global_threshold_abs)
        if not leaks:
            break
        steps += 1
        if steps > max_steps:
            break

        leak = max(leaks, key=lambda item: item["utility"])
        pattern_key = leak["pattern_key"]
        definition = sensitive_defs[pattern_key]
        tx, window_state = _best_global_transaction(
            sanitized_windows,
            definition["items"],
            item_scores,
            global_beta,
            global_gamma,
        )
        if tx is None or window_state is None:
            break

        victim_item = choose_victim_item(tx, definition["items"], item_scores)
        if victim_item is None:
            break

        needed = int(leak["utility"] - global_threshold_abs + 1)
        before = int(tx["item_utils"].get(str(victim_item), 0))
        delta = decrease_item_utility(tx, victim_item, needed)
        if delta <= 0:
            break
        after = int(tx["item_utils"].get(str(victim_item), 0))
        utility_reduced += delta
        modifications.append(
            _modification_record(
                window_state["window_key"],
                tx,
                victim_item,
                before,
                after,
                delta,
                "global",
                pattern_key,
            )
        )
        _refresh_window_pattern_state(window_state, sensitive_defs)

    post_utils = compute_global_pattern_utils(sanitized_windows, sensitive_defs)
    return modifications, int(utility_reduced), pre_leaks, _global_leaks(post_utils, global_threshold_abs)


def build_modified_transactions_df(
    original_db: dict,
    sanitized_windows: dict,
    item_mapping: dict | None,
) -> pd.DataFrame:
    """Build item-level before/after utility deltas for modified transactions."""
    normalized_mapping = normalize_item_mapping(item_mapping)
    original_lookup = {}
    for window_key, window_payload in original_db.get("windows", {}).items():
        for tx in window_payload.get("transactions", []):
            prepared = tx_prepare(tx)
            original_lookup[(str(window_key), prepared["tid"])] = prepared

    rows = []
    for window_key, window_state in sanitized_windows.items():
        for tid, sanitized_tx in window_state["tx_lookup"].items():
            original_tx = original_lookup.get((str(window_key), str(tid)))
            if original_tx is None:
                continue
            item_ids = sorted(
                {
                    int(item)
                    for item in list(original_tx.get("items", [])) + list(sanitized_tx.get("items", []))
                }
            )
            for item_id in item_ids:
                before = int(original_tx.get("item_utils", {}).get(str(item_id), 0))
                after = int(sanitized_tx.get("item_utils", {}).get(str(item_id), 0))
                delta = before - after
                if delta == 0:
                    continue
                mapping = normalized_mapping.get(item_id, {})
                rows.append(
                    {
                        "window": str(window_key),
                        "tid": str(tid),
                        "invoice_no": str(sanitized_tx.get("invoice_no", "")),
                        "item_id": item_id,
                        "stock_code": mapping.get("stock_code", str(item_id)),
                        "description": mapping.get("description", ""),
                        "before_utility": before,
                        "after_utility": after,
                        "delta": delta,
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


def phase2_sanitize(
    phase1_output: dict,
    temporal_db: dict,
    item_mapping: dict | None = None,
    local_ratio: float = 0.015,
    global_ratio: float = 0.015,
    output_dir: str | Path = "app_outputs",
    global_beta: float = 0.25,
    global_gamma: float = 0.75,
) -> tuple[dict, dict, pd.DataFrame]:
    """Run Phase 2 local and global utility sanitization."""
    sensitive_defs = collect_sensitive_patterns(phase1_output)
    item_scores = phase1_output.get("item_scores", {})
    phase1_windows = phase1_output.get("windows", {})
    windows = temporal_db.get("windows", {})
    sanitized_windows = {}
    local_reports = {}
    all_modifications: list[dict] = []
    local_violations_after: list[dict] = []
    local_reduced = 0

    for window_key, window_payload in sorted(windows.items()):
        state = init_window_state(
            window_key,
            window_payload,
            sensitive_defs,
            phase1_windows.get(window_key, {}),
        )
        local_threshold_abs = _threshold_abs(
            int(window_payload.get("total_utility", 0)),
            float(local_ratio),
        )
        modifications, utility_reduced, violations = apply_local_temporal_sanitization(
            state,
            sensitive_defs,
            local_threshold_abs,
            item_scores,
            global_beta,
            global_gamma,
        )
        sanitized_windows[str(window_key)] = state
        all_modifications.extend(modifications)
        local_violations_after.extend(violations)
        local_reduced += utility_reduced
        local_reports[str(window_key)] = {
            "window": str(window_key),
            "targets": len(state["local_targets"]),
            "modifications": len(modifications),
            "utility_reduced": int(utility_reduced),
            "local_violations": len(violations),
            "local_threshold_abs": int(local_threshold_abs),
        }

    original_total_utility = int(
        sum(int(window.get("total_utility", 0)) for window in windows.values())
    )
    global_threshold_abs = _threshold_abs(original_total_utility, float(global_ratio))
    global_modifications, global_reduced, pre_global_leaks, post_global_leaks = patch_global_leakage(
        sanitized_windows,
        sensitive_defs,
        global_threshold_abs,
        item_scores,
        global_beta,
        global_gamma,
    )
    all_modifications.extend(global_modifications)
    total_utility_reduced = int(local_reduced + global_reduced)

    sanitized_db = _build_sanitized_db(temporal_db, sanitized_windows)
    modified_transactions_df = build_modified_transactions_df(
        temporal_db,
        sanitized_windows,
        item_mapping,
    )

    sanitized_total_utility = int(
        sum(window["total_utility"] for window in sanitized_db["windows"].values())
    )
    utility_loss_rate = (
        total_utility_reduced / original_total_utility if original_total_utility else 0.0
    )
    summary = {
        "sensitive_patterns": len(sensitive_defs),
        "local_violations_after": len(local_violations_after),
        "pre_patch_global_leaks": len(pre_global_leaks),
        "post_patch_global_leaks": len(post_global_leaks),
        "total_utility_reduced": total_utility_reduced,
        "utility_loss_rate": utility_loss_rate,
        "modified_transactions": int(modified_transactions_df["tid"].nunique())
        if not modified_transactions_df.empty
        else 0,
        "original_total_utility": original_total_utility,
        "sanitized_total_utility": sanitized_total_utility,
        "local_ratio": float(local_ratio),
        "global_ratio": float(global_ratio),
        "global_threshold_abs": int(global_threshold_abs),
        "global_beta": float(global_beta),
        "global_gamma": float(global_gamma),
    }

    phase2_output = {
        "metadata": {
            "local_ratio": float(local_ratio),
            "global_ratio": float(global_ratio),
            "global_beta": float(global_beta),
            "global_gamma": float(global_gamma),
        },
        "summary": summary,
        "sensitive_patterns": _serialize_sensitive_defs(sensitive_defs),
        "sanitized_db": sanitized_db,
        "local_reports": list(local_reports.values()),
        "global_report": {
            "pre_patch_global_leaks": pre_global_leaks,
            "post_patch_global_leaks": post_global_leaks,
            "global_utility_reduced": int(global_reduced),
        },
        "modifications": all_modifications,
    }

    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    _write_json(output_path / "phase2_sanitized_db.json", sanitized_db)
    _write_json(output_path / "phase2_summary.json", summary)
    modified_transactions_df.to_csv(output_path / "modified_transactions.csv", index=False)
    _write_sanitized_retail(output_path / "sanitized_retail.txt", sanitized_db)

    return phase2_output, summary, modified_transactions_df


def _refresh_window_pattern_state(window_state: dict, sensitive_defs: dict) -> None:
    """Refresh inverted index and pattern utilities after a utility reduction."""
    transactions = list(window_state["tx_lookup"].values())
    window_state["item_to_tids"] = build_item_to_tids(transactions)
    for key, definition in sensitive_defs.items():
        tids = get_tids_for_pattern(definition["items"], window_state["item_to_tids"])
        window_state["pattern_tids"][key] = tids
        window_state["pattern_utils"][key] = recompute_pattern_utility_in_window(
            window_state["tx_lookup"],
            tids,
            definition["items"],
        )


def _best_transaction(
    tx_lookup: dict[str, dict],
    tids: set[str],
    pattern_items: tuple[int, ...],
    item_scores: dict,
    global_beta: float,
    global_gamma: float,
) -> dict | None:
    """Return the best transaction to modify for a pattern."""
    candidates = [
        tx_lookup[tid]
        for tid in tids
        if get_pattern_utility_in_tx(tx_lookup[tid], pattern_items) > 0
    ]
    if not candidates:
        return None
    return max(
        candidates,
        key=lambda tx: score_transaction(
            tx,
            pattern_items,
            item_scores,
            related_sensitive_count=1,
            global_beta=global_beta,
            global_gamma=global_gamma,
        ),
    )


def _best_global_transaction(
    sanitized_windows: dict,
    pattern_items: tuple[int, ...],
    item_scores: dict,
    global_beta: float,
    global_gamma: float,
) -> tuple[dict | None, dict | None]:
    """Return the best transaction/window pair for global leakage patching."""
    best_tx = None
    best_window = None
    best_score = None
    for window_state in sanitized_windows.values():
        tids = get_tids_for_pattern(pattern_items, window_state["item_to_tids"])
        for tid in tids:
            tx = window_state["tx_lookup"][tid]
            if get_pattern_utility_in_tx(tx, pattern_items) <= 0:
                continue
            score = score_transaction(
                tx,
                pattern_items,
                item_scores,
                related_sensitive_count=1,
                global_beta=global_beta,
                global_gamma=global_gamma,
            )
            if best_score is None or score > best_score:
                best_tx = tx
                best_window = window_state
                best_score = score
    return best_tx, best_window


def _modification_record(
    window_key: str,
    tx: dict,
    item: int,
    before: int,
    after: int,
    delta: int,
    phase: str,
    pattern_key: str,
) -> dict:
    """Build a JSON-safe modification record."""
    return {
        "window": str(window_key),
        "tid": str(tx.get("tid", "")),
        "invoice_no": str(tx.get("invoice_no", "")),
        "item_id": int(item),
        "before_utility": int(before),
        "after_utility": int(after),
        "delta": int(delta),
        "phase": phase,
        "pattern_key": pattern_key,
    }


def _local_violations(
    window_state: dict,
    sensitive_defs: dict,
    local_threshold_abs: int,
) -> list[dict]:
    """Return local target patterns still above the hiding threshold."""
    violations = []
    for pattern_key in sorted(window_state["local_targets"]):
        utility = int(window_state["pattern_utils"].get(pattern_key, 0))
        if utility >= local_threshold_abs:
            violations.append(
                {
                    "window": window_state["window_key"],
                    "pattern_key": pattern_key,
                    "items": list(sensitive_defs[pattern_key]["items"]),
                    "utility": utility,
                    "threshold": int(local_threshold_abs),
                }
            )
    return violations


def _global_leaks(pattern_utils: dict[str, int], global_threshold_abs: int) -> list[dict]:
    """Return sensitive patterns still above the global threshold."""
    return [
        {
            "pattern_key": pattern_key,
            "utility": int(utility),
            "threshold": int(global_threshold_abs),
        }
        for pattern_key, utility in sorted(pattern_utils.items())
        if int(utility) >= global_threshold_abs
    ]


def _build_sanitized_db(original_db: dict, sanitized_windows: dict) -> dict:
    """Build JSON-safe sanitized DB payload."""
    windows = {}
    for window_key, state in sorted(sanitized_windows.items()):
        transactions = [
            serialize_tx(tx)
            for tx in sorted(state["tx_lookup"].values(), key=lambda item: item["tid"])
        ]
        total_utility = int(sum(tx["transaction_utility"] for tx in transactions))
        windows[str(window_key)] = {
            "window_key": str(window_key),
            "total_utility": total_utility,
            "num_transactions": len(transactions),
            "transactions": transactions,
        }
    return {
        "metadata": {
            **original_db.get("metadata", {}),
            "sanitized": True,
        },
        "windows": windows,
    }


def _serialize_sensitive_defs(sensitive_defs: dict) -> list[dict]:
    """Serialize sensitive pattern definitions."""
    return [
        {
            "pattern_key": key,
            "items": list(payload["items"]),
            "peak_windows": sorted(payload["peak_windows"]),
            "local_target_windows": sorted(payload["local_target_windows"]),
        }
        for key, payload in sorted(sensitive_defs.items())
    ]


def _write_sanitized_retail(path: Path, sanitized_db: dict) -> None:
    """Write sanitized transactions in a simple HUIM text format."""
    lines = []
    for window in sanitized_db.get("windows", {}).values():
        for tx in window.get("transactions", []):
            items = [int(item) for item in tx.get("items", [])]
            utilities = [int(tx.get("item_utils", {}).get(str(item), 0)) for item in items]
            lines.append(
                f"{' '.join(map(str, items))}:{int(sum(utilities))}:{' '.join(map(str, utilities))}"
            )
    path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")


def _write_json(path: Path, payload: dict) -> None:
    """Write JSON using UTF-8."""
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _threshold_abs(total_utility: int, ratio: float) -> int:
    """Compute a positive threshold when utility exists."""
    if total_utility <= 0:
        return 0
    return max(1, int(total_utility * ratio))


def _pattern_key(items: tuple[int, ...]) -> str:
    """Return a canonical pattern key."""
    return " ".join(str(int(item)) for item in sorted(items))


def _item_score(item: int | None, item_scores: dict) -> float:
    """Return item score from Phase 1 item_scores output."""
    if item is None:
        return 0.0
    payload = item_scores.get(str(int(item))) or item_scores.get(int(item)) or {}
    return float(payload.get("score", 0.0)) if isinstance(payload, dict) else 0.0
