"""Thin client for the Meta (Facebook) Marketing API insights endpoint.

Fetches per-ad performance for a time window and normalises the response into
plain dicts keyed by the metric names used elsewhere in this project.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any

import requests

log = logging.getLogger(__name__)

GRAPH_BASE = "https://graph.facebook.com"

# Fields we ask the API for. `actions`, `action_values` and `purchase_roas`
# are arrays we post-process to pull out purchase conversions and ROAS.
INSIGHT_FIELDS = [
    "ad_id",
    "ad_name",
    "campaign_name",
    "adset_name",
    "spend",
    "impressions",
    "reach",
    "clicks",
    "ctr",
    "cpc",
    "cpm",
    "frequency",
    "actions",
    "action_values",
    "purchase_roas",
]

# Action types that represent a purchase, in priority order. Meta often returns
# several overlapping purchase rows (pixel, omni, app); we take the first match
# so we never double-count.
PURCHASE_ACTION_TYPES = [
    "omni_purchase",
    "purchase",
    "offsite_conversion.fb_pixel_purchase",
    "onsite_web_purchase",
    "app_custom_event.fb_mobile_purchase",
]

# Transient HTTP statuses and Meta error codes worth retrying.
_RETRY_STATUSES = {429, 500, 502, 503, 504}
_RETRY_META_CODES = {1, 2, 4, 17, 32, 341, 613}  # rate limit / transient


class MetaApiError(RuntimeError):
    """Raised when the Graph API returns an error we can't recover from."""


class MetaAdsClient:
    def __init__(
        self,
        access_token: str,
        account_path: str,
        api_version: str = "v21.0",
        max_retries: int = 5,
        session: requests.Session | None = None,
    ) -> None:
        self.access_token = access_token
        self.account_path = account_path
        self.api_version = api_version
        self.max_retries = max_retries
        self.session = session or requests.Session()

    # -- public API -------------------------------------------------------

    def fetch_ad_insights(self, since: str, until: str) -> list[dict[str, Any]]:
        """Return one normalised metrics dict per ad for the ``[since, until]``
        window (inclusive, ``YYYY-MM-DD`` strings), aggregated over the range."""
        url = f"{GRAPH_BASE}/{self.api_version}/{self.account_path}/insights"
        params: dict[str, Any] | None = {
            "level": "ad",
            "fields": ",".join(INSIGHT_FIELDS),
            "time_range": json.dumps({"since": since, "until": until}),
            "limit": 200,
            "access_token": self.access_token,
        }

        rows: list[dict[str, Any]] = []
        page = 0
        while url:
            page += 1
            payload = self._get(url, params)
            batch = payload.get("data", [])
            rows.extend(batch)
            log.info("Fetched page %d (%d ads, %d total)", page, len(batch), len(rows))
            # The `next` cursor is a fully-formed URL with its own query string.
            url = payload.get("paging", {}).get("next")
            params = None

        return [self.parse_row(r) for r in rows]

    # -- internals --------------------------------------------------------

    def _get(self, url: str, params: dict[str, Any] | None) -> dict[str, Any]:
        last_exc: Exception | None = None
        for attempt in range(1, self.max_retries + 1):
            try:
                resp = self.session.get(url, params=params, timeout=60)
            except requests.RequestException as exc:  # network blip
                last_exc = exc
                self._sleep(attempt, reason=str(exc))
                continue

            if resp.status_code == 200:
                return resp.json()

            # Try to surface Meta's structured error.
            code, message = self._extract_error(resp)
            retryable = resp.status_code in _RETRY_STATUSES or code in _RETRY_META_CODES
            if retryable and attempt < self.max_retries:
                self._sleep(attempt, reason=f"HTTP {resp.status_code}: {message}")
                continue

            raise MetaApiError(
                f"Meta API request failed (HTTP {resp.status_code}, code {code}): {message}"
            )

        raise MetaApiError(f"Meta API request failed after retries: {last_exc}")

    @staticmethod
    def _extract_error(resp: requests.Response) -> tuple[int | None, str]:
        try:
            err = resp.json().get("error", {})
            return err.get("code"), err.get("message", resp.text[:300])
        except ValueError:
            return None, resp.text[:300]

    def _sleep(self, attempt: int, reason: str) -> None:
        delay = min(2 ** attempt, 60)
        log.warning("Retrying in %ds (attempt %d): %s", delay, attempt, reason)
        time.sleep(delay)

    # -- parsing ----------------------------------------------------------

    @classmethod
    def parse_row(cls, row: dict[str, Any]) -> dict[str, Any]:
        actions = cls._to_map(row.get("actions"))
        action_values = cls._to_map(row.get("action_values"))

        purchases = cls._first_purchase(actions)
        purchase_value = cls._first_purchase(action_values)

        spend = _to_float(row.get("spend"))
        roas = cls._first_roas(row.get("purchase_roas"))
        if roas is None:
            roas = round(purchase_value / spend, 4) if spend else 0.0

        return {
            "ad_id": row.get("ad_id", ""),
            "ad_name": row.get("ad_name") or row.get("ad_id", ""),
            "campaign_name": row.get("campaign_name", ""),
            "adset_name": row.get("adset_name", ""),
            "spend": round(spend, 2),
            "impressions": _to_int(row.get("impressions")),
            "reach": _to_int(row.get("reach")),
            "clicks": _to_int(row.get("clicks")),
            "ctr": round(_to_float(row.get("ctr")), 4),
            "cpc": round(_to_float(row.get("cpc")), 4),
            "cpm": round(_to_float(row.get("cpm")), 4),
            "frequency": round(_to_float(row.get("frequency")), 4),
            "purchases": int(purchases),
            "purchase_value": round(purchase_value, 2),
            "roas": round(roas, 4),
        }

    @staticmethod
    def _to_map(items: Any) -> dict[str, float]:
        out: dict[str, float] = {}
        if isinstance(items, list):
            for item in items:
                atype = item.get("action_type")
                if atype is not None:
                    out[atype] = _to_float(item.get("value"))
        return out

    @staticmethod
    def _first_purchase(values: dict[str, float]) -> float:
        for atype in PURCHASE_ACTION_TYPES:
            if atype in values:
                return values[atype]
        return 0.0

    @staticmethod
    def _first_roas(items: Any) -> float | None:
        if isinstance(items, list) and items:
            return _to_float(items[0].get("value"))
        return None


def _to_float(value: Any) -> float:
    try:
        return float(value) if value not in (None, "") else 0.0
    except (TypeError, ValueError):
        return 0.0


def _to_int(value: Any) -> int:
    return int(_to_float(value))
