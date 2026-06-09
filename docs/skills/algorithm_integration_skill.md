# Skill: Integrate TA-PPHUIM Algorithm Logic

## When to use

Use this skill when modifying Phase 1, Phase 2, or Phase 3 algorithm modules.

## Goal

Integrate algorithm logic without breaking the TA-PPHUIM pipeline assumptions.

## Pipeline assumptions

Phase 0:
- Uses filtered temporal DB.
- Utility = round(Quantity * UnitPrice).
- Windows are monthly.

Phase 1:
- Runs EFIM/PAMI per window.
- Applies TWU pruning if enabled.
- Recomputes candidate utilities across all windows.
- Computes support_windows and peakness_ratio.
- Selects Peak-Sensitive HUIs.
- Produces `phase1_peak_shui.json`.

Phase 2:
- Reads Phase 1 output and temporal DB.
- Reduces item utility to hide sensitive patterns.
- Does not delete whole transactions as the main operation.
- Tracks modified transactions.
- Checks global leakage.
- Produces `phase2_sanitized_db.json`.

Phase 3:
- Independently recomputes local/global utilities.
- Verifies local hiding and global leakage.
- Computes utility loss and modified transaction rate.

## Rules

1. Do not change output JSON schemas without explaining migration.
2. Do not hard-code threshold values inside algorithm functions.
3. Always pass thresholds as parameters.
4. Keep Phase 2 and Phase 3 compatible.
5. If PAMI is not installed, fail gracefully.
6. Do not claim profit; use utility or revenue contribution.

## Done when

- The phase runs on a small sample.
- Output JSON can be consumed by the next phase.
- Summary metrics are returned.
- Errors are clear and actionable.

Cách gọi:

Use the TA-PPHUIM Algorithm Integration skill. Implement phase2_sanitization.py based on the existing Phase 2 logic, but make it app-friendly: no Kaggle paths, no print-only output, return dicts/DataFrames, and save outputs to app_outputs/.

