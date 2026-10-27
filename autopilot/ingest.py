"""Read a portfolio export (xlsx sheet or csv) into a raw DataFrame.

Nothing is fixed here beyond the column headers: cleaning lives in clean.py so
every change to a value is logged.
"""
from __future__ import annotations

import hashlib
import re
from pathlib import Path

import pandas as pd


class IngestError(ValueError):
    pass


def _normalise_header(name: object) -> str:
    text = str(name).strip().lower()
    text = re.sub(r"[^a-z0-9]+", "_", text)
    return text.strip("_")


def file_fingerprint(path: Path, sheet: str | None = None) -> str:
    """Stable id for an input (file bytes + sheet), used to skip re-processing."""
    digest = hashlib.sha256(Path(path).read_bytes())
    if sheet:
        digest.update(f"::{sheet}".encode())
    return digest.hexdigest()[:16]


def read_portfolio(path: str | Path, sheet: str | None, rules: dict) -> pd.DataFrame:
    path = Path(path)
    if not path.exists():
        raise IngestError(f"Input not found: {path}")

    suffix = path.suffix.lower()
    if suffix in {".xlsx", ".xlsm", ".xls"}:
        xls = pd.ExcelFile(path)
        if sheet is None:
            # Default to the first sheet that looks like account rows
            sheet = next((s for s in xls.sheet_names if s.lower() != "readme"), xls.sheet_names[0])
        if sheet not in xls.sheet_names:
            raise IngestError(f"Sheet '{sheet}' not in {path.name}. Sheets: {xls.sheet_names}")
        df = pd.read_excel(xls, sheet_name=sheet, dtype=object)
    elif suffix in {".csv", ".tsv", ".txt"}:
        sep = "\t" if suffix == ".tsv" else None
        df = pd.read_csv(path, dtype=object, sep=sep, engine="python")
    else:
        raise IngestError(f"Unsupported file type: {suffix}")

    cfg = rules["data"]
    df.columns = [_normalise_header(c) for c in df.columns]
    df = df.rename(columns={k: v for k, v in cfg.get("column_aliases", {}).items() if k in df.columns and v not in df.columns})
    df = df.dropna(how="all")  # trailing empty rows from Excel

    missing = [c for c in cfg["required"] if c not in df.columns]
    if missing:
        raise IngestError(f"{path.name}[{sheet}] is missing required columns: {missing}")

    # Optional columns that are absent become blank so downstream code is uniform
    for col in cfg["numeric"] + cfg["text"]:
        if col not in df.columns:
            df[col] = pd.NA

    df.attrs["source"] = f"{path.name}" + (f"[{sheet}]" if sheet else "")
    df.attrs["fingerprint"] = file_fingerprint(path, sheet)
    return df.reset_index(drop=True)
