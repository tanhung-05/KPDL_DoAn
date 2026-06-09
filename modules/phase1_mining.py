"""Phase 1 EFIM mining and Peak-Sensitive HUI selection logic.

The functions here are UI-free and operate on the temporal DB generated
by Phase 0 preprocessing.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from modules.efim_runner import (
    check_pami_available,
    run_efim_on_spmf,
    twu_prune_transactions,
    write_window_spmf,
)
from modules.mining import MiningConfig


def is_pami_available() -> bool:
    """Return True when PAMI EFIM can be imported."""
    return bool(check_pami_available()["available"])


def pattern_key(items: list[int] | tuple[int, ...] | set[int]) -> str:
    """Return a canonical key with sorted integer item IDs joined by spaces."""
    return " ".join(str(item) for item in sorted(int(item) for item in items))


def transaction_contains_pattern(tx: dict, pattern_items: list[int]) -> bool:
    """Return whether a transaction contains all pattern items."""
    tx_items = {int(item) for item in tx.get("items", [])}
    return set(int(item) for item in pattern_items).issubset(tx_items)


def get_pattern_utility_in_tx(tx: dict, pattern_items: list[int]) -> int:
    """Return the sum utility of pattern items in a transaction.

    If the transaction does not contain the full pattern, the utility is zero.
    """
    if not transaction_contains_pattern(tx, pattern_items):
        return 0

    item_utils = tx.get("item_utils", {})
    total = 0
    for item in pattern_items:
        if item in item_utils:
            total += int(item_utils[item])
        else:
            total += int(item_utils.get(str(item), 0))
    return total


def recompute_candidate_utilities_across_windows(
    temporal_db: dict,
    candidate_patterns: list[dict],
) -> dict:
    """Compute exact utility for every candidate pattern in every window."""
    window_keys = _window_keys(temporal_db)
    candidates = _merge_candidate_patterns(candidate_patterns)
    result: dict[str, dict] = {}

    for key, candidate in candidates.items():
        items = candidate["items"]
        utilities_by_window = {}
        for window_key in window_keys:
            window = temporal_db.get("windows", {}).get(window_key, {})
            transactions = window.get("transactions", [])
            utility = sum(
                get_pattern_utility_in_tx(tx, items)
                for tx in transactions
            )
            utilities_by_window[window_key] = int(utility)

        result[key] = {
            "pattern_key": key,
            "items": items,
            "utilities_by_window": utilities_by_window,
            "source_windows": sorted(candidate.get("source_windows", [])),
            "max_mined_utility": int(candidate.get("max_mined_utility", 0)),
        }

    return result


def compute_temporal_stats(
    candidate_utils_by_window: dict,
    window_total_utils: dict[str, int],
) -> dict:
    """Compute temporal support, ratios, peakness, and utility traces."""
    stats: dict[str, dict] = {}
    ordered_windows = sorted(window_total_utils)

    for key, payload in candidate_utils_by_window.items():
        utilities_by_window = {
            window: int(payload["utilities_by_window"].get(window, 0))
            for window in ordered_windows
        }
        ratios_by_window = {
            window: (
                utilities_by_window[window] / window_total_utils[window]
                if window_total_utils.get(window, 0)
                else 0.0
            )
            for window in ordered_windows
        }
        positive_windows = [
            window for window, utility in utilities_by_window.items() if utility > 0
        ]
        support_windows = len(positive_windows)
        max_window = max(
            ordered_windows,
            key=lambda window: (utilities_by_window[window], ratios_by_window[window]),
        ) if ordered_windows else None
        max_utility = int(utilities_by_window[max_window]) if max_window else 0
        max_ratio = float(ratios_by_window[max_window]) if max_window else 0.0
        positive_ratios = [
            ratios_by_window[window]
            for window in positive_windows
            if ratios_by_window[window] > 0
        ]
        mean_ratio = float(sum(positive_ratios) / len(positive_ratios)) if positive_ratios else 0.0
        peakness_ratio = float(max_ratio / mean_ratio) if mean_ratio else 0.0
        peak_windows = [
            window
            for window, ratio in ratios_by_window.items()
            if ratio == max_ratio and ratio > 0
        ]

        stats[key] = {
            "pattern_key": key,
            "items": payload["items"],
            "support_windows": support_windows,
            "max_window": max_window,
            "max_utility": max_utility,
            "max_ratio": max_ratio,
            "mean_ratio": mean_ratio,
            "peakness_ratio": peakness_ratio,
            "peak_windows": peak_windows,
            "utilities_by_window": utilities_by_window,
            "ratios_by_window": ratios_by_window,
            "source_windows": payload.get("source_windows", []),
            "max_mined_utility": int(payload.get("max_mined_utility", 0)),
        }

    return stats


def select_peak_sensitive_huis(
    pattern_stats: dict,
    window_total_utils: dict[str, int],
    sensitive_ratio: float,
    min_peakness_ratio: float,
    min_support_windows: int,
    max_selected_per_window: int,
) -> tuple[list[dict], list[dict]]:
    """Filter and select Peak-Sensitive HUIs per temporal window."""
    survivors = []
    for payload in pattern_stats.values():
        ratios_by_window = payload.get("ratios_by_window", {})
        reaches_sensitive = any(
            ratio >= sensitive_ratio for ratio in ratios_by_window.values()
        )
        if (
            payload.get("support_windows", 0) >= min_support_windows
            and payload.get("peakness_ratio", 0.0) >= min_peakness_ratio
            and reaches_sensitive
        ):
            survivors.append(payload)

    selected: list[dict] = []
    for window_key in sorted(window_total_utils):
        window_candidates = []
        for payload in survivors:
            window_utility = int(payload["utilities_by_window"].get(window_key, 0))
            window_ratio = float(payload["ratios_by_window"].get(window_key, 0.0))
            if window_utility > 0 and window_ratio >= sensitive_ratio:
                window_candidates.append(
                    {
                        "pattern_key": payload["pattern_key"],
                        "items": payload["items"],
                        "selected_window": window_key,
                        "window_utility": window_utility,
                        "window_ratio": window_ratio,
                        "support_windows": payload["support_windows"],
                        "max_window": payload["max_window"],
                        "max_utility": payload["max_utility"],
                        "max_ratio": payload["max_ratio"],
                        "mean_ratio": payload["mean_ratio"],
                        "peakness_ratio": payload["peakness_ratio"],
                        "peak_windows": payload["peak_windows"],
                        "utilities_by_window": payload["utilities_by_window"],
                    }
                )

        window_candidates.sort(
            key=lambda item: (
                item["window_ratio"],
                item["window_utility"],
                item["peakness_ratio"],
            ),
            reverse=True,
        )
        selected.extend(window_candidates[:max_selected_per_window])

    return selected, survivors


def compute_item_scores(selected_shuis: list[dict]) -> tuple[dict, list[dict]]:
    """Compute item-level scores from selected sensitive patterns."""
    item_scores: dict[str, dict] = {}
    for pattern in selected_shuis:
        score = float(pattern.get("window_ratio", 0.0)) * float(pattern.get("peakness_ratio", 0.0))
        for item in pattern.get("items", []):
            key = str(int(item))
            current = item_scores.setdefault(
                key,
                {
                    "ItemID": int(item),
                    "score": 0.0,
                    "selected_count": 0,
                    "windows": [],
                    "patterns": [],
                },
            )
            current["score"] += score
            current["selected_count"] += 1
            current["windows"].append(pattern.get("selected_window"))
            current["patterns"].append(pattern.get("pattern_key"))

    for payload in item_scores.values():
        payload["windows"] = sorted(set(window for window in payload["windows"] if window))
        payload["patterns"] = sorted(set(pattern for pattern in payload["patterns"] if pattern))

    item_scores_flat = sorted(
        item_scores.values(),
        key=lambda item: (item["score"], item["selected_count"]),
        reverse=True,
    )
    return item_scores, item_scores_flat


def phase1_mine(
    temporal_db: dict,
    item_mapping: dict | None,
    params: dict,
    output_dir: str | Path = "app_outputs",
) -> dict:
    """Run Phase 1 EFIM mining and Peak-Sensitive HUI selection."""
    availability = check_pami_available()
    if not availability["available"]:
        raise RuntimeError(
            f"PAMI EFIM is not available. {availability['install_hint']} "
            f"Import error: {availability['error']}"
        )

    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    work_dir = output_path / "phase1_windows"
    work_dir.mkdir(parents=True, exist_ok=True)

    mining_ratio = float(params.get("mining_ratio", 0.01))
    sensitive_ratio = float(params.get("sensitive_ratio", 0.015))
    candidate_mining_ratio = float(params.get("candidate_mining_ratio", mining_ratio))
    min_peakness_ratio = float(params.get("min_peakness_ratio", 1.5))
    min_support_windows = int(params.get("min_support_windows", 2))
    max_selected_per_window = int(params.get("max_selected_per_window", 30))
    max_patterns_per_window = int(params.get("max_patterns_per_window", 3000))
    enable_twu_pruning = bool(params.get("enable_twu_pruning", True))

    windows_payload = temporal_db.get("windows", {})
    window_total_utils = {
        window_key: int(window.get("total_utility", 0))
        for window_key, window in sorted(windows_payload.items())
    }

    candidate_patterns: list[dict] = []
    phase_windows: dict[str, dict] = {}
    total_raw_patterns = 0
    failed_windows = []

    for window_key, window in sorted(windows_payload.items()):
        transactions = window.get("transactions", [])
        total_utility = int(window.get("total_utility", 0))
        min_util_abs = int(total_utility * candidate_mining_ratio)
        mining_transactions = transactions
        twu_stats = None

        if enable_twu_pruning:
            mining_transactions, twu_stats = twu_prune_transactions(
                transactions,
                min_util_abs,
            )

        spmf_path = work_dir / f"{window_key}.txt"
        efim_output_path = work_dir / f"{window_key}_patterns.txt"
        raw_patterns = []
        error = None

        try:
            write_window_spmf(mining_transactions, spmf_path)
            if mining_transactions and total_utility > 0:
                raw_patterns = run_efim_on_spmf(
                    spmf_path,
                    min_util_abs,
                    efim_output_path,
                )
        except RuntimeError as exc:
            error = str(exc)
            failed_windows.append(window_key)

        raw_patterns = sorted(
            raw_patterns,
            key=lambda pattern: pattern.get("utility", 0),
            reverse=True,
        )[:max_patterns_per_window]
        total_raw_patterns += len(raw_patterns)

        for raw_pattern in raw_patterns:
            candidate_patterns.append(
                {
                    "items": raw_pattern["items"],
                    "pattern_key": pattern_key(raw_pattern["items"]),
                    "utility": int(raw_pattern["utility"]),
                    "source_window": window_key,
                }
            )

        phase_windows[window_key] = {
            "window_key": window_key,
            "total_utility": total_utility,
            "num_transactions": int(window.get("num_transactions", len(transactions))),
            "min_util_abs": min_util_abs,
            "candidate_mining_ratio": candidate_mining_ratio,
            "enable_twu_pruning": enable_twu_pruning,
            "twu_stats": twu_stats,
            "raw_patterns_count": len(raw_patterns),
            "raw_patterns": raw_patterns,
            "error": error,
        }

    candidate_utils = recompute_candidate_utilities_across_windows(
        temporal_db,
        candidate_patterns,
    )
    temporal_stats = compute_temporal_stats(candidate_utils, window_total_utils)
    selected_shuis, survivors = select_peak_sensitive_huis(
        temporal_stats,
        window_total_utils,
        sensitive_ratio=sensitive_ratio,
        min_peakness_ratio=min_peakness_ratio,
        min_support_windows=min_support_windows,
        max_selected_per_window=max_selected_per_window,
    )
    item_scores, item_scores_flat = compute_item_scores(selected_shuis)

    for window_key in phase_windows:
        phase_windows[window_key]["selected_shuis"] = [
            pattern
            for pattern in selected_shuis
            if pattern.get("selected_window") == window_key
        ]

    all_pattern_stats = sorted(
        temporal_stats.values(),
        key=lambda payload: (payload["max_ratio"], payload["max_utility"]),
        reverse=True,
    )

    mining_summary = {
        "total_raw_patterns": total_raw_patterns,
        "unique_candidates": len(candidate_utils),
        "survivors": len(survivors),
        "selected_patterns": len(selected_shuis),
        "failed_windows": len(failed_windows),
        "failed_window_keys": failed_windows,
        "scored_items": len(item_scores_flat),
    }

    phase1_output = {
        "metadata": {
            "params": {
                "mining_ratio": mining_ratio,
                "sensitive_ratio": sensitive_ratio,
                "candidate_mining_ratio": candidate_mining_ratio,
                "min_peakness_ratio": min_peakness_ratio,
                "min_support_windows": min_support_windows,
                "max_selected_per_window": max_selected_per_window,
                "max_patterns_per_window": max_patterns_per_window,
                "enable_twu_pruning": enable_twu_pruning,
            },
            "num_windows": len(phase_windows),
            "item_mapping_available": item_mapping is not None,
        },
        "windows": phase_windows,
        "all_pattern_stats": all_pattern_stats,
        "survivors": survivors,
        "selected_shuis": selected_shuis,
        "item_scores": item_scores,
        "item_scores_flat": item_scores_flat,
        "mining_summary": mining_summary,
    }

    output_file = output_path / "phase1_peak_shui.json"
    output_file.write_text(
        json.dumps(phase1_output, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    phase1_output["metadata"]["output_file"] = str(output_file)
    output_file.write_text(
        json.dumps(phase1_output, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    return phase1_output


def _window_keys(temporal_db: dict) -> list[str]:
    """Return sorted temporal DB window keys."""
    windows = temporal_db.get("windows", {})
    return sorted(windows)


def _merge_candidate_patterns(candidate_patterns: list[dict]) -> dict:
    """Merge duplicate candidate patterns mined from different windows."""
    merged: dict[str, dict] = {}
    for candidate in candidate_patterns:
        items = [int(item) for item in candidate.get("items", [])]
        if not items:
            continue
        key = pattern_key(items)
        payload = merged.setdefault(
            key,
            {
                "pattern_key": key,
                "items": [int(item) for item in key.split()],
                "source_windows": set(),
                "max_mined_utility": 0,
            },
        )
        if candidate.get("source_window"):
            payload["source_windows"].add(candidate["source_window"])
        payload["max_mined_utility"] = max(
            int(payload["max_mined_utility"]),
            int(candidate.get("utility", 0)),
        )

    for payload in merged.values():
        payload["source_windows"] = sorted(payload["source_windows"])
    return merged
