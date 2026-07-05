"""Entry point: read a Meta Ads Manager CSV export and write each ad's metrics
into a Notion database, adapting the database columns to whatever the export
contains.

Usage:
    python -m src.sync path/to/export.csv
    DRY_RUN=true python -m src.sync path/to/export.csv   # preview, don't write
    python -m src.sync                                    # uses CSV_PATH env var
"""

from __future__ import annotations

import logging
import os
import sys
from datetime import date

from .config import Config, ConfigError, load_config
from .csv_parser import CsvError, ExportData, parse_meta_csv
from .notion_writer import NotionApiError, NotionWriter

log = logging.getLogger("meta_ads_sync")


def resolve_csv_path(argv: list[str]) -> str:
    if len(argv) > 1 and argv[1].strip():
        return argv[1]
    env_path = os.environ.get("CSV_PATH", "").strip()
    if env_path:
        return env_path
    raise ConfigError(
        "No CSV file given. Pass the export path as an argument "
        "(python -m src.sync export.csv) or set CSV_PATH."
    )


def _row_spend(row: dict) -> float | None:
    """Best-effort spend for the min-spend filter: the first numeric field whose
    column name looks like an amount-spent column."""
    for name, (ntype, value) in row["fields"].items():
        if ntype == "number" and ("amount spent" in name.lower() or "spend" in name.lower()):
            return value
    return None


def run(cfg: Config, csv_path: str) -> int:
    export = parse_meta_csv(csv_path)
    log.info(
        "Parsed %d ad row(s) from %s (skipped %d total/blank row(s)).",
        len(export.rows), csv_path, export.skipped,
    )
    log.info("Detected columns: %s", _describe_columns(export))

    rows = export.rows
    if cfg.min_spend > 0:
        before = len(rows)
        filtered = [r for r in rows if (_row_spend(r) or 0) >= cfg.min_spend]
        if before and len(filtered) == before and all(_row_spend(r) is None for r in rows):
            log.warning("MIN_SPEND set but no spend column found; not filtering.")
        else:
            rows = filtered
            log.info("Filtered to %d/%d ad(s) with spend >= %.2f", len(rows), before, cfg.min_spend)

    if not rows:
        log.warning("No ad rows to sync.")
        return 0

    if cfg.dry_run:
        _print_preview(export, rows)
        log.info("DRY_RUN enabled -- not writing to Notion.")
        return 0

    synced_on = date.today().isoformat()
    writer = NotionWriter(token=cfg.notion_token, database_id=cfg.notion_database_id)
    title_prop = writer.ensure_schema(export)
    log.info("Writing to Notion (title column: %r)...", title_prop)

    created = updated = failed = 0
    for row in rows:
        try:
            outcome = writer.upsert_row(row, export, synced_on=synced_on)
            created += outcome == "created"
            updated += outcome == "updated"
            log.info("  %-8s %s", outcome, row["title"])
        except NotionApiError as exc:
            failed += 1
            log.error("  FAILED  %s: %s", row["title"], exc)

    log.info("Done. %d created, %d updated, %d failed.", created, updated, failed)
    return 1 if failed else 0


def _describe_columns(export: ExportData) -> str:
    parts = []
    if export.has_week_start or export.has_week_ending:
        parts.append("Week Start/Ending (date)")
    for col in export.columns:
        fmt = f", {col.number_format}" if col.ntype == "number" and col.number_format else ""
        parts.append(f"{col.name} ({col.ntype}{fmt})")
    return "; ".join(parts)


def _print_preview(export: ExportData, rows: list[dict]) -> None:
    window = ""
    if rows and (rows[0].get("week_start") or rows[0].get("week_ending")):
        window = f"  ({rows[0].get('week_start')} .. {rows[0].get('week_ending')})"
    print(f"\nWould sync {len(rows)} ad(s){window}:\n")
    numeric_cols = [c.name for c in export.columns if c.ntype == "number"]
    show = numeric_cols[:5]
    header = f"{'Ad':<32}" + "".join(f"{c[:12]:>14}" for c in show)
    print(header)
    print("-" * len(header))
    for row in rows:
        line = f"{row['title'][:30]:<32}"
        for c in show:
            val = row["fields"].get(c, (None, None))[1]
            line += f"{(val if val is not None else 0):>14.2f}" if isinstance(val, (int, float)) else f"{'':>14}"
        print(line)
    print("-" * len(header))
    if numeric_cols:
        totals = f"{'TOTAL':<32}"
        for c in show:
            s = sum((row["fields"].get(c, (None, 0))[1] or 0) for row in rows if isinstance(row["fields"].get(c, (None, None))[1], (int, float)))
            totals += f"{s:>14.2f}"
        print(totals)
    print()


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )
    try:
        cfg = load_config()
        csv_path = resolve_csv_path(sys.argv)
        return run(cfg, csv_path)
    except ConfigError as exc:
        log.error("Configuration error: %s", exc)
        return 2
    except CsvError as exc:
        log.error("Could not read CSV: %s", exc)
        return 2
    except FileNotFoundError as exc:
        log.error("CSV file not found: %s", exc)
        return 2
    except NotionApiError as exc:
        log.error("%s", exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
