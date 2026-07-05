"""Load and validate configuration from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass

# Load a local .env if present. In CI / other environments the variables come
# from the environment directly, so python-dotenv is optional and its absence
# is not an error.
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
    notion_token: str
    notion_database_id: str
    min_spend: float
    dry_run: bool


def load_config() -> Config:
    """Read config from the environment. Notion credentials are only required
    when we're actually going to write (i.e. not a dry run)."""
    dry_run = _get_bool("DRY_RUN", False)
    return Config(
        notion_token=_get("NOTION_TOKEN", required=not dry_run),
        notion_database_id=_get("NOTION_DATABASE_ID", required=not dry_run),
        min_spend=_get_float("MIN_SPEND", 0.0),
        dry_run=dry_run,
    )
