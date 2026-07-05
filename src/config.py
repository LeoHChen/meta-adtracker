"""Load and validate configuration from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass

# Load a local .env if present. In CI the variables come from the environment
# directly, so python-dotenv is optional and its absence is not an error.
try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:  # pragma: no cover - dotenv is optional
    pass


class ConfigError(RuntimeError):
    """Raised when required configuration is missing or malformed."""


def _get(name: str, default: str | None = None, required: bool = False) -> str:
    value = os.environ.get(name, default)
    if required and not value:
        raise ConfigError(
            f"Missing required environment variable: {name}. "
            f"See .env.example for the full list."
        )
    return value or ""


def _get_bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _get_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ConfigError(f"{name} must be an integer, got {raw!r}") from exc


def _get_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    try:
        return float(raw)
    except ValueError as exc:
        raise ConfigError(f"{name} must be a number, got {raw!r}") from exc


@dataclass(frozen=True)
class Config:
    meta_access_token: str
    meta_ad_account_id: str
    meta_api_version: str
    notion_token: str
    notion_database_id: str
    lookback_days: int
    min_spend: float
    dry_run: bool

    @property
    def account_path(self) -> str:
        """Ad account id normalised to the ``act_<id>`` form the API expects."""
        acct = self.meta_ad_account_id.strip()
        return acct if acct.startswith("act_") else f"act_{acct}"


def load_config(require_notion: bool = True) -> Config:
    """Read config from the environment.

    ``require_notion`` is ``False`` for dry runs where we never touch Notion.
    """
    dry_run = _get_bool("DRY_RUN", False)
    need_notion = require_notion and not dry_run

    lookback = _get_int("LOOKBACK_DAYS", 7)
    if lookback < 1:
        raise ConfigError(f"LOOKBACK_DAYS must be >= 1, got {lookback}")

    return Config(
        meta_access_token=_get("META_ACCESS_TOKEN", required=True),
        meta_ad_account_id=_get("META_AD_ACCOUNT_ID", required=True),
        meta_api_version=_get("META_API_VERSION", default="v21.0"),
        notion_token=_get("NOTION_TOKEN", required=need_notion),
        notion_database_id=_get("NOTION_DATABASE_ID", required=need_notion),
        lookback_days=lookback,
        min_spend=_get_float("MIN_SPEND", 0.0),
        dry_run=dry_run,
    )
