# Manual Test Checklist

Use this checklist before final demo submission.

## Startup

Backend:

```powershell
python -m uvicorn backend.app.main:app --reload
```

Frontend:

```powershell
cd frontend
npm.cmd run dev
```

- `GET http://127.0.0.1:8000/health` returns `{"status":"ok"}`.
- React dashboard opens at `http://127.0.0.1:5173`.
- PAMI status is shown in the top-right status pill.

## Data

- Click **Dữ liệu demo**.
- Confirm raw metrics and preview table render.
- Upload a comma-separated CSV with required columns.
- Upload a semicolon-separated CSV with decimal comma values.
- Invalid CSV shows a clear missing-column or parser error.

## Preprocessing

- Run preprocessing with default `max_transaction_len = 30`.
- Confirm transactions, utility, window count, max-length impact, and preview rows render.
- Confirm `temporal_db.json` and `item_mapping.json` appear in the output list for the run.

## Phase 1 Mining

- If PAMI is not installed, Phase 1 shows an install hint and does not crash.
- If PAMI is installed, run Phase 1 on the demo dataset.
- Confirm mining summary and selected PSHUI table render.
- Confirm `phase1_peak_shui.json` appears in outputs.

## Phase 2 Sanitization

- Run Phase 2 after Phase 1.
- Confirm sensitive pattern count, global leak count, utility reduction, and modified transactions render.
- Confirm these files appear in outputs:
  - `phase2_sanitized_db.json`
  - `phase2_summary.json`
  - `modified_transactions.csv`
  - `sanitized_retail.txt`

## Phase 3 Verification

- Run Phase 3 after Phase 2.
- Confirm PASS/FAIL verdict renders.
- Confirm window metrics render.
- Confirm these files appear in outputs:
  - `phase3_verification_report.json`
  - `phase3_window_metrics.csv`
  - `phase3_pattern_metrics.csv`

## Explorer And Export

- Open **Explorer**.
- Click **Explorer** to load modified transactions and sensitive patterns.
- Click **Xem giao dịch đầu tiên** when modified transactions are available.
- Confirm before/after item utility rows render.
- Click output file links and confirm downloads work.
