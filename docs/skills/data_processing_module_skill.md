# Skill: Build a Data Processing Module

## When to use

Use this skill when implementing logic in `modules/`.

## Goal

Create clean, reusable Python functions for TA-PPHUIM data processing.

## Inputs

The user will provide:
- Module name
- Function names
- Input/output requirements
- Expected JSON/DataFrame schemas

## Steps

1. Put pure logic in functions.
2. Do not use UI framework code inside this module unless explicitly requested.
3. Add type hints where practical.
4. Copy input DataFrames before modifying them.
5. Validate required columns.
6. Return structured outputs: dict, DataFrame, or tuple.
7. Avoid hidden global state.
8. Avoid hard-coded file paths.
9. Keep output schema documented in docstrings.
10. Raise clear ValueError for invalid inputs.

## Constraints

- Do not mix UI and processing logic.
- Do not silently drop rows without counting them in a report.
- Do not change algorithm defaults unless requested.
- Utility means `round(Quantity * UnitPrice)`, not profit.

## Done when

- Functions can be imported without frontend or API side effects.
- Each public function has a docstring.
- Edge cases are handled.
- The caller can display the report through the FastAPI/React application.

Cách gọi:

Use the Data Processing Module Builder skill. Implement modules/preprocessing.py with preprocess_retail_df, compute_max_len_impact, and write_json_outputs. Follow the temporal_db schema already described in AGENTS.md.
