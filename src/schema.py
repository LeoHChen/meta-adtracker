"""Notion property helpers and the small set of *fixed* columns.

The design is schema-adaptive: whatever columns appear in the Meta CSV export
become Notion columns automatically (see ``csv_parser`` for type inference and
``notion_writer`` for on-the-fly column creation). Only a few columns are fixed
and always present:

- the **title** column (the ad name) — Notion requires exactly one title; we
  discover its actual name from the target database at write time;
- **Week Start** / **Week Ending** — the reporting window, when the export
  includes reporting dates;
- **Synced On** — the date the row was written, for provenance and as a dedupe
  fallback when an export has no reporting dates.

This module also centralises the translation between our internal type names
(``title`` / ``rich_text`` / ``number`` / ``date``) and Notion's payload shapes,
so the parser, the database-setup helper and the writer all agree.
"""

from __future__ import annotations

from typing import Any

# Fixed property names.
DEFAULT_TITLE_PROP = "Ad Name"
WEEK_START_PROP = "Week Start"
WEEK_END_PROP = "Week Ending"
SYNCED_PROP = "Synced On"

# Notion caps title / rich_text content at 2000 characters per item.
MAX_TEXT = 2000


def notion_property_spec(ntype: str, number_format: str | None = None) -> dict[str, Any]:
    """Return the *schema* definition for a property (used when creating a
    database or adding a column to one)."""
    if ntype == "title":
        return {"title": {}}
    if ntype == "rich_text":
        return {"rich_text": {}}
    if ntype == "date":
        return {"date": {}}
    if ntype == "number":
        return {"number": {"format": number_format or "number"}}
    raise ValueError(f"Unsupported Notion property type: {ntype}")


def notion_property_value(ntype: str, value: Any) -> dict[str, Any]:
    """Return the *value* payload for a property (used when writing a row)."""
    if ntype == "title":
        return {"title": [{"text": {"content": _text(value) or "(unnamed ad)"}}]}
    if ntype == "rich_text":
        return {"rich_text": [{"text": {"content": _text(value)}}]}
    if ntype == "number":
        return {"number": value if isinstance(value, (int, float)) else None}
    if ntype == "date":
        return {"date": {"start": value} if value else None}
    raise ValueError(f"Unsupported Notion property type: {ntype}")


def _text(value: Any) -> str:
    return ("" if value is None else str(value))[:MAX_TEXT]
