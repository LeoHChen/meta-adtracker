"""Entry point: fetch last week's per-ad metrics from Meta and write them to
Notion. Run with ``python -m src.sync``."""

from __future__ import annotations

import logging
import sys
from datetime import date, timedelta

from .config import Config, ConfigError, load_config
from .meta_client import MetaAdsClient, MetaApiError
from .notion_writer import NotionApiError, NotionWriter

log = logging.getLogger("meta_ads_sync")


def compute_window(lookback_days: int, today: date | None = None) -> tuple[str, str]:
    """Return (since, until) as YYYY-MM-DD for the reporting window.

    The window ends yesterday (Meta's numbers for the current day are still
    settling) and spans ``lookback_days`` days inclusive.
    """
    today = today or date.today()
    until = today - timedelta(days=1)
    since = until - timedelta(days=lookback_days - 1)
    return since.isoformat(), until.isoformat()


def run(cfg: Config) -> int:
    since, until = compute_window(cfg.lookback_days)
    report_date = date.today().isoformat()
    log.info("Reporting window: %s .. %s (report date %s)", since, until, report_date)

    meta = MetaAdsClient(
        access_token=cfg.meta_access_token,
        account_path=cfg.account_path,
        api_version=cfg.meta_api_version,
    )
    ads = meta.fetch_ad_insights(since, until)

    if cfg.min_spend > 0:
        before = len(ads)
        ads = [a for a in ads if a["spend"] >= cfg.min_spend]
        log.info("Filtered to %d/%d ads with spend >= %.2f", len(ads), before, cfg.min_spend)

    if not ads:
        log.warning("No ad data returned for this window. Nothing to sync.")
        return 0

    if cfg.dry_run:
        _print_table(ads, since, until)
        log.info("DRY_RUN enabled -- not writing to Notion.")
        return 0

    writer = NotionWriter(token=cfg.notion_token, database_id=cfg.notion_database_id)
    created = updated = failed = 0
    for ad in ads:
        try:
            outcome = writer.upsert_ad(ad, week_ending=until, report_date=report_date)
            created += outcome == "created"
            updated += outcome == "updated"
            log.info("  %-8s %s ($%.2f spend)", outcome, ad["ad_name"], ad["spend"])
        except NotionApiError as exc:
            failed += 1
            log.error("  FAILED  %s: %s", ad["ad_name"], exc)

    log.info("Done. %d created, %d updated, %d failed.", created, updated, failed)
    return 1 if failed else 0


def _print_table(ads, since: str, until: str) -> None:
    log.info("Metrics for %s .. %s (%d ads):", since, until, len(ads))
    header = f"{'Ad':<40} {'Spend':>10} {'Impr':>10} {'Clicks':>8} {'CTR%':>7} {'ROAS':>7}"
    print(header)
    print("-" * len(header))
    for a in ads:
        name = a["ad_name"][:38]
        print(
            f"{name:<40} {a['spend']:>10.2f} {a['impressions']:>10} "
            f"{a['clicks']:>8} {a['ctr']:>7.2f} {a['roas']:>7.2f}"
        )
    totals_spend = sum(a["spend"] for a in ads)
    print("-" * len(header))
    print(f"{'TOTAL':<40} {totals_spend:>10.2f}")


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )
    try:
        cfg = load_config()
        return run(cfg)
    except ConfigError as exc:
        log.error("Configuration error: %s", exc)
        return 2
    except (MetaApiError, NotionApiError) as exc:
        log.error("%s", exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
