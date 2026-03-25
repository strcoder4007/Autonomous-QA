"""Read ticket CSV/Excel files into raw row dicts."""

from __future__ import annotations

import csv
import logging
from pathlib import Path

log = logging.getLogger(__name__)


def _read_csv(path: Path) -> list[dict[str, str]]:
    for encoding in ("utf-8-sig", "cp1252"):
        try:
            rows: list[dict[str, str]] = []
            with open(path, newline="", encoding=encoding) as f:
                reader = csv.DictReader(f)
                for row in reader:
                    rows.append({k: (v or "") for k, v in row.items()})
            if encoding != "utf-8-sig":
                log.warning("CSV decoded with fallback encoding '%s'", encoding)
            return rows
        except UnicodeDecodeError:
            log.warning("Encoding '%s' failed for %s, trying next", encoding, path)

    raise RuntimeError(f"Could not decode {path} with utf-8-sig or cp1252")


def _read_excel(path: Path) -> list[dict[str, str]]:
    try:
        import openpyxl
    except ImportError:
        raise RuntimeError("openpyxl is required to read Excel files: pip install openpyxl")

    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    ws = wb.active
    rows: list[dict[str, str]] = []

    row_iter = iter(ws.rows)
    try:
        header_row = next(row_iter)
    except StopIteration:
        wb.close()
        return rows

    headers = [str(cell.value).strip() if cell.value is not None else "" for cell in header_row]

    for row in row_iter:
        row_dict = {
            headers[i]: (str(row[i].value) if row[i].value is not None else "")
            for i in range(len(headers))
        }
        rows.append(row_dict)

    wb.close()
    return rows


def read_tickets(path: str | Path) -> list[dict[str, str]]:
    """Read a CSV or Excel file and return each row as a dict of column→value strings."""
    p = Path(path)
    if not p.is_file():
        raise FileNotFoundError(f"Ticket file not found: {p}")

    suffix = p.suffix.lower()
    if suffix == ".csv":
        rows = _read_csv(p)
    elif suffix in (".xlsx", ".xls"):
        rows = _read_excel(p)
    else:
        raise ValueError(f"Unsupported extension '{suffix}'. Expected .csv, .xlsx, or .xls")

    log.info("Read %d rows from %s", len(rows), p)
    return rows
