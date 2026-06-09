"""Reusable EFIM/PAMI helpers for Phase 1 high-utility itemset mining.

This module intentionally contains no UI code. It writes temporal
transactions to SPMF HUIM format, optionally applies TWU pruning, and wraps the
PAMI EFIM implementation when it is installed.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any


INSTALL_HINT = "Install PAMI with `pip install PAMI` to run EFIM mining."


def check_pami_available() -> dict:
    """Return availability metadata for the PAMI EFIM implementation."""
    try:
        from PAMI.highUtilityPattern.basic.EFIM import EFIM  # noqa: F401
    except Exception as exc:  # pragma: no cover - depends on environment
        return {
            "available": False,
            "error": str(exc),
            "install_hint": INSTALL_HINT,
        }

    return {
        "available": True,
        "error": None,
        "install_hint": INSTALL_HINT,
    }


def write_window_spmf(transactions: list[dict], output_path: str | Path) -> Path:
    """Write transactions in SPMF HUIM format: ``items:TU:itemutils``.

    Each transaction must contain ``items`` and ``item_utils``. ``item_utils`` may
    use integer or string item IDs as keys. Item utilities are aligned to the
    item order written in the first field.
    """
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    lines = []
    for transaction in transactions:
        items = [int(item) for item in transaction.get("items", [])]
        if not items:
            continue
        item_utils_source = transaction.get("item_utils", {})
        item_utils = [_lookup_item_utility(item_utils_source, item) for item in items]
        transaction_utility = int(sum(item_utils))

        items_text = " ".join(str(item) for item in items)
        utils_text = " ".join(str(int(utility)) for utility in item_utils)
        lines.append(f"{items_text}:{transaction_utility}:{utils_text}")

    path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
    return path


def twu_prune_transactions(
    transactions: list[dict],
    min_util_abs: int,
) -> tuple[list[dict], dict]:
    """Prune items whose transaction-weighted utility is below ``min_util_abs``.

    TWU is computed by adding the original transaction utility to every item
    contained in that transaction. Empty transactions after pruning are removed.
    """
    before_tx = len(transactions)
    before_lengths = [len(transaction.get("items", [])) for transaction in transactions]
    before_items = {
        int(item)
        for transaction in transactions
        for item in transaction.get("items", [])
    }

    twu: dict[int, int] = {}
    for transaction in transactions:
        items = [int(item) for item in transaction.get("items", [])]
        transaction_utility = _transaction_utility(transaction)
        for item in set(items):
            twu[item] = twu.get(item, 0) + transaction_utility

    kept_items = {item for item, item_twu in twu.items() if item_twu >= min_util_abs}
    pruned_transactions = []
    for transaction in transactions:
        item_utils_source = transaction.get("item_utils", {})
        kept_tx_items = [
            int(item)
            for item in transaction.get("items", [])
            if int(item) in kept_items
        ]
        if not kept_tx_items:
            continue

        kept_item_utils = {
            str(item): _lookup_item_utility(item_utils_source, item)
            for item in kept_tx_items
        }
        pruned = dict(transaction)
        pruned["items"] = kept_tx_items
        pruned["item_utils"] = kept_item_utils
        pruned["transaction_utility"] = int(sum(kept_item_utils.values()))
        pruned_transactions.append(pruned)

    after_lengths = [len(transaction.get("items", [])) for transaction in pruned_transactions]
    after_items = {
        int(item)
        for transaction in pruned_transactions
        for item in transaction.get("items", [])
    }
    stats = {
        "before_items": len(before_items),
        "after_items": len(after_items),
        "before_avg_len": _avg(before_lengths),
        "after_avg_len": _avg(after_lengths),
        "before_max_len": max(before_lengths) if before_lengths else 0,
        "after_max_len": max(after_lengths) if after_lengths else 0,
        "kept_tx": len(pruned_transactions),
        "before_tx": before_tx,
    }
    return pruned_transactions, stats


def run_efim_on_spmf(
    spmf_path: str | Path,
    min_util_abs: int,
    output_path: str | Path | None = None,
) -> list[dict]:
    """Run PAMI EFIM on an SPMF HUIM file and return parsed patterns.

    Raises:
        RuntimeError: If PAMI EFIM is unavailable or mining fails.
    """
    availability = check_pami_available()
    if not availability["available"]:
        raise RuntimeError(
            f"PAMI EFIM is not available. {availability['install_hint']} "
            f"Import error: {availability['error']}"
        )

    try:
        from PAMI.highUtilityPattern.basic.EFIM import EFIM
    except Exception as exc:  # pragma: no cover - guarded above
        raise RuntimeError(f"PAMI EFIM import failed. {INSTALL_HINT}") from exc

    spmf_file = Path(spmf_path)
    if not spmf_file.exists():
        raise RuntimeError(f"SPMF input file does not exist: {spmf_file}")

    try:
        algorithm = EFIM(str(spmf_file), int(min_util_abs), sep=" ")
        algorithm.mine()
    except Exception as exc:
        raise RuntimeError(f"EFIM mining failed: {exc}") from exc

    if output_path is not None:
        output_file = Path(output_path)
        output_file.parent.mkdir(parents=True, exist_ok=True)
        try:
            algorithm.save(str(output_file))
        except Exception as exc:
            raise RuntimeError(f"EFIM output save failed: {exc}") from exc

    patterns = _patterns_from_algorithm(algorithm)
    if patterns:
        return patterns

    if output_path is not None and Path(output_path).exists():
        return _parse_patterns_from_text(Path(output_path).read_text(encoding="utf-8"))

    return []


def _patterns_from_algorithm(algorithm: Any) -> list[dict]:
    """Extract and normalize patterns from a PAMI EFIM object."""
    try:
        raw_patterns = algorithm.getPatterns()
    except Exception:
        return []

    if not raw_patterns:
        return []

    patterns = []
    if isinstance(raw_patterns, dict):
        for raw_items, raw_utility in raw_patterns.items():
            pattern = _pattern_from_items_and_utility(raw_items, raw_utility)
            if pattern is not None:
                patterns.append(pattern)
    elif isinstance(raw_patterns, list):
        for raw_pattern in raw_patterns:
            if isinstance(raw_pattern, dict):
                items = raw_pattern.get("items") or raw_pattern.get("pattern")
                utility = raw_pattern.get("utility") or raw_pattern.get("Utility")
                pattern = _pattern_from_items_and_utility(items, utility)
            else:
                pattern = _parse_pattern_line(str(raw_pattern))
            if pattern is not None:
                patterns.append(pattern)

    return _dedupe_patterns(patterns)


def _parse_patterns_from_text(text: str) -> list[dict]:
    """Parse EFIM output text into normalized pattern dictionaries."""
    patterns = []
    for line in text.splitlines():
        pattern = _parse_pattern_line(line.strip())
        if pattern is not None:
            patterns.append(pattern)
    return _dedupe_patterns(patterns)


def _parse_pattern_line(line: str) -> dict | None:
    """Parse one common EFIM output line."""
    if not line:
        return None

    if "#UTIL:" in line:
        items_text, utility_text = line.split("#UTIL:", 1)
        return _pattern_from_items_and_utility(items_text.strip(), utility_text.strip())

    if ":" in line:
        items_text, utility_text = line.split(":", 1)
        utility_text = utility_text.strip().split()[0] if utility_text.strip() else ""
        return _pattern_from_items_and_utility(items_text.strip(), utility_text)

    return None


def _pattern_from_items_and_utility(raw_items: Any, raw_utility: Any) -> dict | None:
    """Normalize raw pattern fields to ``items``, ``utility``, and ``pattern_key``."""
    items = _parse_items(raw_items)
    if not items:
        return None
    items = sorted(items)

    try:
        utility = int(float(str(raw_utility).strip()))
    except (TypeError, ValueError):
        return None

    pattern_key = " ".join(str(item) for item in items)
    return {
        "items": items,
        "utility": utility,
        "pattern_key": pattern_key,
    }


def _parse_items(raw_items: Any) -> list[int]:
    """Parse pattern item IDs from strings/lists/tuples."""
    if raw_items is None:
        return []
    if isinstance(raw_items, (list, tuple, set)):
        return [int(item) for item in raw_items]
    text = str(raw_items).replace("\t", " ").strip()
    if not text:
        return []
    return [int(part) for part in text.split() if part]


def _dedupe_patterns(patterns: list[dict]) -> list[dict]:
    """Deduplicate patterns by pattern_key while preserving order."""
    seen = set()
    deduped = []
    for pattern in patterns:
        key = pattern["pattern_key"]
        if key in seen:
            continue
        seen.add(key)
        deduped.append(pattern)
    return deduped


def _lookup_item_utility(item_utils: dict, item: int) -> int:
    """Read an item utility from dicts with string or integer keys."""
    if item in item_utils:
        return int(item_utils[item])
    if str(item) in item_utils:
        return int(item_utils[str(item)])
    raise ValueError(f"Missing utility for item {item}.")


def _transaction_utility(transaction: dict) -> int:
    """Return transaction utility, recomputing from item_utils if needed."""
    if "transaction_utility" in transaction:
        return int(transaction["transaction_utility"])
    item_utils = transaction.get("item_utils", {})
    return int(sum(int(value) for value in item_utils.values()))


def _avg(values: list[int]) -> float:
    """Return average length with an empty-list fallback."""
    if not values:
        return 0.0
    return float(sum(values) / len(values))
