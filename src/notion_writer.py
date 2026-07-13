"""Write parsed Meta metrics into a Notion database, adapting the database
schema to whatever columns the export contains.

Flow:
1. ``ensure_schema`` reads the target database, discovers its title property,
   and adds any columns present in the export but missing from the database.
2. ``upsert_row`` writes one ad's row, keyed on (title, reporting window) so
   re-uploading the same week updates in place instead of duplicating.
"""

from __future__ import annotations

import logging
import time
from typing import Any

import requests

from .csv_parser import ExportData
from .customizations import ONE_ROW_PER_AD
from .schema import (
    SYNCED_PROP,
    WEEK_END_PROP,
    WEEK_START_PROP,
    notion_property_spec,
    notion_property_value,
)

log = logging.getLogger(__name__)

NOTION_BASE = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"
_RETRY_STATUSES = {429, 500, 502, 503, 504}


class NotionApiError(RuntimeError):
    """Raised when the Notion API returns an unrecoverable error."""


class NotionWriter:
    def __init__(
        self,
        token: str,
        database_id: str,
        max_retries: int = 5,
        session: requests.Session | None = None,
    ) -> None:
        self.database_id = database_id
        self.max_retries = max_retries
        self.session = session or requests.Session()
        self.session.headers.update(
            {
                "Authorization": f"Bearer {token}",
                "Notion-Version": NOTION_VERSION,
                "Content-Type": "application/json",
            }
        )
        self.title_prop = "Name"  # replaced by ensure_schema()

    # -- schema -----------------------------------------------------------

    def ensure_schema(self, export: ExportData) -> str:
        """Add any missing columns to the database. Returns the title property
        name (discovered from the database, since Notion allows only one)."""
        db = self._request("GET", f"/databases/{self.database_id}", None)
        existing = db.get("properties", {})
        self.title_prop = _find_title_prop(existing)

        to_add: dict[str, Any] = {}
        if export.has_week_start and WEEK_START_PROP not in existing:
            to_add[WEEK_START_PROP] = notion_property_spec("date")
        if export.has_week_ending and WEEK_END_PROP not in existing:
            to_add[WEEK_END_PROP] = notion_property_spec("date")
        if SYNCED_PROP not in existing:
            to_add[SYNCED_PROP] = notion_property_spec("date")
        for col in export.columns:
            if col.name != self.title_prop and col.name not in existing and col.name not in to_add:
                to_add[col.name] = notion_property_spec(col.ntype, col.number_format)

        if to_add:
            self._request("PATCH", f"/databases/{self.database_id}", {"properties": to_add})
            log.info("Added %d new column(s) to Notion: %s", len(to_add), ", ".join(to_add))
        return self.title_prop

    # -- rows -------------------------------------------------------------

    def upsert_row(self, row: dict[str, Any], export: ExportData, synced_on: str) -> str:
        """Create or update one ad's row. Returns "created" or "updated"."""
        props: dict[str, Any] = {
            self.title_prop: notion_property_value("title", row["title"]),
            SYNCED_PROP: notion_property_value("date", synced_on),
        }
        if export.has_week_start:
            props[WEEK_START_PROP] = notion_property_value("date", row.get("week_start"))
        if export.has_week_ending:
            props[WEEK_END_PROP] = notion_property_value("date", row.get("week_ending"))
        for name, (ntype, value) in row["fields"].items():
            if name != self.title_prop:
                props[name] = notion_property_value(ntype, value)

        existing_id = self._find_existing(row, export, synced_on)
        if existing_id:
            self._request("PATCH", f"/pages/{existing_id}", {"properties": props})
            return "updated"

        self._request(
            "POST",
            "/pages",
            {"parent": {"database_id": self.database_id}, "properties": props},
        )
        return "created"

    def _find_existing(
        self, row: dict[str, Any], export: ExportData, synced_on: str
    ) -> str | None:
        conditions: list[dict[str, Any]] = [
            {"property": self.title_prop, "title": {"equals": row["title"]}}
        ]
        # ONE_ROW_PER_AD: match on ad name alone, so every sync updates the same
        # single row per ad. Otherwise scope the match to the reporting period.
        if not ONE_ROW_PER_AD:
            if export.has_week_ending and row.get("week_ending"):
                conditions.append(
                    {"property": WEEK_END_PROP, "date": {"equals": row["week_ending"]}}
                )
            if export.has_week_start and row.get("week_start"):
                conditions.append(
                    {"property": WEEK_START_PROP, "date": {"equals": row["week_start"]}}
                )
            # No reporting window in the export: fall back to the sync date so a
            # same-day re-run updates rather than duplicates.
            if not (export.has_week_start or export.has_week_ending):
                conditions.append({"property": SYNCED_PROP, "date": {"equals": synced_on}})

        payload = self._request(
            "POST",
            f"/databases/{self.database_id}/query",
            {"filter": {"and": conditions}, "page_size": 1},
        )
        results = payload.get("results", [])
        return results[0]["id"] if results else None

    # -- transport --------------------------------------------------------

    def _request(self, method: str, path: str, body: dict[str, Any] | None) -> dict[str, Any]:
        url = f"{NOTION_BASE}{path}"
        for attempt in range(1, self.max_retries + 1):
            try:
                resp = self.session.request(method, url, json=body, timeout=60)
            except requests.RequestException as exc:
                self._sleep(attempt, str(exc))
                continue

            if resp.status_code < 300:
                return resp.json()

            message = self._extract_error(resp)
            if resp.status_code in _RETRY_STATUSES and attempt < self.max_retries:
                retry_after = resp.headers.get("Retry-After")
                delay = float(retry_after) if retry_after else min(2 ** attempt, 30)
                log.warning("Retrying Notion %s in %.0fs: %s", path, delay, message)
                time.sleep(delay)
                continue

            raise NotionApiError(
                f"Notion {method} {path} failed (HTTP {resp.status_code}): {message}"
            )

        raise NotionApiError(f"Notion {method} {path} failed after retries")

    @staticmethod
    def _extract_error(resp: requests.Response) -> str:
        try:
            return resp.json().get("message", resp.text[:300])
        except ValueError:
            return resp.text[:300]

    def _sleep(self, attempt: int, reason: str) -> None:
        delay = min(2 ** attempt, 30)
        log.warning("Retrying Notion request in %.0fs (attempt %d): %s", delay, attempt, reason)
        time.sleep(delay)


def _find_title_prop(properties: dict[str, Any]) -> str:
    for name, spec in properties.items():
        if spec.get("type") == "title" or "title" in spec:
            return name
    # A well-formed Notion database always has a title; fall back defensively.
    return "Name"
