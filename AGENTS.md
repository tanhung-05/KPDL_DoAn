# AGENTS.md — TA-PPHUIM FastAPI + React System

## Project goal

Maintain a FastAPI backend and React frontend that demonstrate the full
TA-PPHUIM pipeline:

1. Upload retail transaction CSV.
2. Analyze raw input data.
3. Preprocess data into temporal transaction windows.
4. Run EFIM-based High Utility Itemset Mining.
5. Select Peak-Sensitive HUIs.
6. Sanitize sensitive patterns by reducing item utilities.
7. Verify local hiding, global leakage prevention, utility loss, and modified transactions.
8. Let users inspect before/after transactions and export results.

## Tech stack

- Python
- FastAPI
- Pandas
- NumPy
- JSON/CSV outputs
- Optional PAMI for EFIM
- React
- TypeScript
- Vite

Do not reintroduce Streamlit, Flask, Django, or a database unless explicitly requested.

## Repository layout

- `backend/app/`: FastAPI application, schemas, and run storage helpers.
- `frontend/`: React + TypeScript dashboard.
- `modules/`: reusable Python pipeline logic.
- `app_outputs/runs/`: generated outputs grouped by `run_id`.
- `README.md`: setup and run instructions.
- `requirements.txt`: backend dependencies.

## Engineering rules

- Keep frontend UI code in `frontend/src/`.
- Keep API code in `backend/app/`.
- Keep algorithm/data-processing logic in `modules/`.
- Avoid hard-coded Kaggle paths.
- Use `app_outputs/runs/{run_id}/` for generated files.
- Do not load external datasets automatically.
- Do not silently change algorithm thresholds.
- If changing a parameter default, explain why.
- Use clear API errors when a previous phase has not run.
- Do not crash if PAMI is not installed; return installation guidance instead.
- Preserve Vietnamese-friendly labels in frontend UI where appropriate.

## Output files

Save generated outputs per run:

- `raw.csv`
- `raw_summary.json`
- `temporal_db.json`
- `item_mapping.json`
- `preprocess_report.json`
- `tx_before_filter.csv`
- `tx_after_filter.csv`
- `phase1_peak_shui.json`
- `phase2_sanitized_db.json`
- `phase2_summary.json`
- `phase3_verification_report.json`
- `modified_transactions.csv`
- `sanitized_retail.txt`
- `phase3_window_metrics.csv`
- `phase3_pattern_metrics.csv`

## Algorithm assumptions

Utility is computed as:

`UtilityInt = round(Quantity * UnitPrice)`

This represents transaction value / revenue contribution, not profit.

Default demo parameters:

- `max_transaction_len = 30`
- `mining_ratio = 0.01`
- `sensitive_ratio = 0.015`
- `candidate_mining_ratio = 0.015`
- `min_peakness_ratio = 1.5`
- `min_support_windows = 2`
- `max_selected_per_window = 30`

Warn users that lower utility thresholds can generate many patterns and slow down EFIM.

## Done means

For each task:

1. Code compiles.
2. Imports are valid.
3. Backend can start with `python -m uvicorn backend.app.main:app --reload`.
4. Frontend builds with `npm.cmd run build` from `frontend/`.
5. New UI handles missing prior phase gracefully.
6. The response lists changed files.
7. The response tells how to test the change.

## Response style

When finishing a task, respond with:

- Files changed
- What was implemented
- How to test
- Any limitations or TODOs
