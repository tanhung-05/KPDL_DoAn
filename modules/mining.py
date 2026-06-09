"""Phase 1 mining utilities for EFIM/PAMI and Peak-Sensitive HUI selection.

This module will detect optional PAMI availability, run EFIM per temporal
window, build raw patterns/candidates/survivors, score items, and select
Peak-Sensitive High Utility Itemsets using user-configurable thresholds.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class MiningConfig:
    """Configuration for Phase 1 HUI mining and sensitive pattern selection."""

    mining_ratio: float = 0.01
    sensitive_ratio: float = 0.015
    candidate_mining_ratio: float = 0.015
    min_peakness_ratio: float = 1.5
    min_support_windows: int = 2
    max_selected_per_window: int = 30
    max_patterns_per_window: int | None = None


def is_pami_available() -> bool:
    """Return whether PAMI can be imported in the current environment."""
    try:
        import PAMI  # noqa: F401
    except ImportError:
        return False
    return True

