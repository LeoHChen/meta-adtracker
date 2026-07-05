"""Write per-ad metrics into a Notion database.

Uses an upsert strategy keyed on (Ad ID, Week Ending): if a row for that ad and
week already exists it is updated in place, otherwise a new row is created. This
makes re-running the sync for the same week idempotent.
"""

from __future__ import annotations

import logging
import time
from typing import Any

import requests

from .schema import DEDUPE_ID_PROP, PROPERTIES, WEEK_PROP

log = logging.getLogger(__name__)

NOTION_BASE = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"
_RETRY_STATUSES = {429, 500, 502, 503, 504}

# Notion caps rich_text / title content at 2000 characters per item.
_MAX_TEXT = 2000


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

    # -- public API -------------------------------------------------------

    def upsert_ad(self, ad: dict[str, Any], week_ending: str, report_date: str) -> str:
        """Create or update the row for one ad/week. Returns "created" or "updated"."""
        record = {**ad, "week_ending": week_ending, "report_date": report_date}
        props = self._build_properties(record)

        existing_id = self._find_existing(ad["ad_id"], week_ending)
        if existing_id:
            self._request("PATCH", f"/pages/{existing_id}", {"properties": props})
            return "updated"

        self._request(
            "POST",
            "/pages",
            {"parent": {"database_id": self.database_id}, "properties": props},
        )
        return "created"

    # -- internals --------------------------------------------------------

    def _find_existing(self, ad_id: str, week_ending: str) -> str | None:
        body = {
            "filter": {
                "and": [
                    {"property": DEDUPE_ID_PROP, "rich_text": {"equals": ad_id}},
                    {"property": WEEK_PROP, "date": {"equals": week_ending}},
                ]
            },
            "page_size": 1,
        }
        payload = self._request(
            "POST", f"/databases/{self.database_id}/query", body
        )
        results = payload.get("results", [])
        return results[0]["id"] if results else None

    def _build_properties(self, record: dict[str, Any]) -> dict[str, Any]:
        props: dict[str, Any] = {}
        for key, name, ntype, _fmt in PROPERTIES:
            value = record.get(key)
            props[name] = _notion_value(ntype, value)
        return props

    def _request(self, method: str, path: str, body: dict[str, Any]) -> dict[str, Any]:
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
                # Honour Retry-After for 429s when present.
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


def _notion_value(ntype: str, value: Any) -> dict[str, Any]:
    """Convert a raw metric value into a Notion property value object."""
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
    return ("" if value is None else str(value))[:_MAX_TEXT]
