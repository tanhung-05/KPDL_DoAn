"""Filesystem storage helpers for backend runs.

The backend keeps each uploaded or generated dataset under its own run folder
inside app_outputs/runs so multiple runs do not overwrite each other.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

import pandas as pd


RUNS_DIR = Path("app_outputs") / "runs"
RAW_CSV_NAME = "raw.csv"
METADATA_NAME = "metadata.json"


def create_run(source: str) -> str:
    """Create and return a new run id."""
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    run_id = uuid4().hex
    run_dir(run_id).mkdir(parents=True, exist_ok=False)
    write_json(
        run_id,
        METADATA_NAME,
        {
            "run_id": run_id,
            "source": source,
            "created_at": datetime.now(timezone.utc).isoformat(),
        },
    )
    return run_id


def run_dir(run_id: str) -> Path:
    """Return the safe path for a run directory."""
    _validate_run_id(run_id)
    return RUNS_DIR / run_id


def require_run_dir(run_id: str) -> Path:
    """Return an existing run directory or raise FileNotFoundError."""
    path = run_dir(run_id)
    if not path.exists() or not path.is_dir():
        raise FileNotFoundError(f"Run not found: {run_id}")
    return path


def save_raw_dataframe(run_id: str, df: pd.DataFrame) -> Path:
    """Persist the normalized raw dataset for a run."""
    path = require_run_dir(run_id) / RAW_CSV_NAME
    df.to_csv(path, index=False)
    return path


def load_raw_dataframe(run_id: str) -> pd.DataFrame:
    """Load the normalized raw dataset for a run."""
    path = require_run_dir(run_id) / RAW_CSV_NAME
    if not path.exists():
        raise FileNotFoundError(f"Raw dataset not found for run: {run_id}")
    return pd.read_csv(path)


def write_json(run_id: str, file_name: str, payload: dict[str, Any]) -> Path:
    """Write JSON payload into a run folder."""
    path = output_path(run_id, file_name)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return path


def read_json(run_id: str, file_name: str) -> dict[str, Any]:
    """Read a JSON output from a run folder."""
    path = output_path(run_id, file_name)
    if not path.exists():
        raise FileNotFoundError(f"Output not found for run {run_id}: {file_name}")
    return json.loads(path.read_text(encoding="utf-8"))


def output_path(run_id: str, file_name: str) -> Path:
    """Return a safe output file path under a run folder."""
    if Path(file_name).name != file_name:
        raise ValueError("Invalid file_name.")
    return require_run_dir(run_id) / file_name


def list_outputs(run_id: str) -> list[str]:
    """List generated output file names for a run."""
    path = require_run_dir(run_id)
    return sorted(item.name for item in path.iterdir() if item.is_file())


def _validate_run_id(run_id: str) -> None:
    """Reject run ids that could escape the runs directory."""
    if not run_id or not run_id.isalnum():
        raise ValueError("Invalid run_id.")
