"""Parse an arbitrary Meta Ads Manager CSV export into a schema-adaptive shape.

Ads Manager lets you choose *any* set of columns to export, and that set may
change from week to week. So this parser does not assume a fixed column list. It:

- finds the entity column (ad / ad set / campaign / account name) to use as the
  row title;
- recognises the reporting-window columns ("Reporting starts" / "Reporting ends",
  or a "Day" column) and maps them to Week Start / Week Ending;
- treats every other column generically, inferring its type (number / date /
  text) from the header and the actual values, and picking a dollar number
  format for cost-like metrics;
- skips the account-total row (the one with a blank ad name) and blank lines.

The result feeds ``notion_writer``, which creates any missing columns in the
target database on the fly.
"""

from __future__ import annotations

import csv
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

log = logging.getLogger(__name__)


class CsvError(RuntimeError):
    """Raised when the CSV can't be parsed into the expected shape."""


# Header (normalised) -> role.
_ENTITY_HEADERS = [
    "ad name",
    "ad set name",
    "adset name",
    "campaign name",
    "account name",
]
_WEEK_START_HEADERS = {"reporting starts", "reporting start"}
_WEEK_END_HEADERS = {"reporting ends", "reporting end"}
_DAY_HEADERS = {"day", "date"}

# Substrings that mark a numeric column as a currency amount.
_DOLLAR_HINTS = (
    "amount spent",
    "spend",
    "cost",
    "cpc",
    "cpm",
    "cpp",
    "budget",
    "revenue",
    "value",
    "price",
)


@dataclass
class Column:
    """A generic (non-title, non-window) column detected in the export."""

    name: str  # Notion property name
    ntype: str  # "number" | "date" | "rich_text"
    number_format: str | None = None


@dataclass
class ExportData:
    columns: list[Column] = field(default_factory=list)
    rows: list[dict[str, Any]] = field(default_factory=list)
    skipped: int = 0
    has_week_start: bool = False
    has_week_ending: bool = False
    title_source_header: str | None = None


def _norm(header: str) -> str:
    return " ".join(str(header).strip().lower().split())


def _pretty_name(header: str) -> str:
    """Notion property name for a generic column. Kept close to Meta's own
    header, with light normalisation for headers whose suffix varies (e.g. the
    currency in 'Amount spent (USD)')."""
    n = _norm(header)
    if n.startswith("amount spent"):
        return "Amount Spent"
    return str(header).strip()


def parse_meta_csv(path: str) -> ExportData:
    with open(path, newline="", encoding="utf-8-sig") as fh:
        raw_rows = list(csv.reader(fh))

    if not raw_rows:
        raise CsvError("The CSV file is empty.")

    headers = raw_rows[0]
    norm = [_norm(h) for h in headers]

    title_idx = _pick_title_index(norm)
    week_start_idx = _first_index(norm, _WEEK_START_HEADERS)
    week_end_idx = _first_index(norm, _WEEK_END_HEADERS)
    # A single "Day"/"Date" column stands in for both ends of the window.
    day_idx = _first_index(norm, _DAY_HEADERS)
    if day_idx is not None:
        week_start_idx = week_start_idx if week_start_idx is not None else day_idx
        week_end_idx = week_end_idx if week_end_idx is not None else day_idx

    special = {title_idx, week_start_idx, week_end_idx}
    generic_indices = [i for i in range(len(headers)) if i not in special]

    # Keep only real data rows: drop blank lines and the account-total row
    # (blank entity/title value).
    data: list[list[str]] = []
    skipped = 0
    for row in raw_rows[1:]:
        if not any(cell.strip() for cell in row):
            continue
        title_val = row[title_idx].strip() if title_idx < len(row) else ""
        if not title_val:
            skipped += 1
            continue
        data.append(row)

    # Infer each generic column's type from its values.
    columns: list[Column] = []
    col_meta: dict[int, tuple[str, str | None, str]] = {}
    for i in generic_indices:
        values = [row[i].strip() for row in data if i < len(row) and row[i].strip()]
        ntype, number_format = _infer_type(norm[i], values)
        name = _pretty_name(headers[i])
        col_meta[i] = (ntype, number_format, name)
        columns.append(Column(name=name, ntype=ntype, number_format=number_format))

    rows: list[dict[str, Any]] = []
    for row in data:
        fields: dict[str, tuple[str, Any]] = {}
        for i in generic_indices:
            ntype, _fmt, name = col_meta[i]
            raw = row[i] if i < len(row) else ""
            fields[name] = (ntype, _convert(ntype, raw))
        rows.append(
            {
                "title": row[title_idx].strip(),
                "week_start": _cell_date(row, week_start_idx),
                "week_ending": _cell_date(row, week_end_idx),
                "fields": fields,
            }
        )

    return ExportData(
        columns=columns,
        rows=rows,
        skipped=skipped,
        has_week_start=week_start_idx is not None,
        has_week_ending=week_end_idx is not None,
        title_source_header=headers[title_idx] if headers else None,
    )


# -- helpers ----------------------------------------------------------------

def _pick_title_index(norm: list[str]) -> int:
    for candidate in _ENTITY_HEADERS:
        for i, header in enumerate(norm):
            if header == candidate:
                return i
    log.warning(
        "No ad/campaign name column found; using the first column (%r) as the title.",
        norm[0] if norm else "",
    )
    return 0


def _first_index(norm: list[str], names: set[str]) -> int | None:
    for i, header in enumerate(norm):
        if header in names:
            return i
    return None


def _infer_type(norm_header: str, values: list[str]) -> tuple[str, str | None]:
    if not values:
        return "rich_text", None
    if all(_to_float(v) is not None for v in values):
        fmt = "dollar" if any(hint in norm_header for hint in _DOLLAR_HINTS) else "number"
        return "number", fmt
    if all(_to_date(v) is not None for v in values):
        return "date", None
    return "rich_text", None


def _convert(ntype: str, raw: str) -> Any:
    if ntype == "number":
        return _to_float(raw)
    if ntype == "date":
        return _to_date(raw)
    return str(raw).strip()


def _cell_date(row: list[str], idx: int | None) -> str | None:
    if idx is None or idx >= len(row):
        return None
    return _to_date(row[idx])


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    text = str(value).strip().replace(",", "").replace("$", "").replace("%", "")
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _to_date(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%Y/%m/%d", "%d/%m/%Y", "%b %d, %Y"):
        try:
            return datetime.strptime(text, fmt).date().isoformat()
        except ValueError:
            continue
    return None
