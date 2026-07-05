# Meta Ads → Notion Weekly Sync

Automatically pulls last week's performance for **every ad** in your Meta (Facebook)
ad account and writes it into a **Notion database** — one row per ad, per week —
every **Friday**, via GitHub Actions.

Re-runs are safe: a row is keyed on _(Ad ID, Week Ending)_, so running again for
the same week **updates** the existing row instead of creating duplicates.

## What gets synced

For each ad, over the reporting window (the 7 days ending yesterday, by default):

| Column | Source |
| --- | --- |
| Ad Name, Ad ID, Campaign, Ad Set | ad metadata |
| Week Ending, Report Date | the window end date / the day it ran |
| Spend | `spend` |
| Impressions, Reach, Clicks | `impressions`, `reach`, `clicks` |
| CTR (%), CPC, CPM, Frequency | `ctr`, `cpc`, `cpm`, `frequency` |
| Purchases, Purchase Value | from `actions` / `action_values` |
| ROAS | `purchase_roas` (falls back to value ÷ spend) |

Want different columns? Edit [`src/schema.py`](src/schema.py) — it's the single
source of truth for both the database setup and the writer. To pull extra Meta
fields, add them to `INSIGHT_FIELDS` and `parse_row` in
[`src/meta_client.py`](src/meta_client.py).

## How it fits together

```
GitHub Actions (cron: Fridays)         .github/workflows/weekly-sync.yml
        │
        ▼
python -m src.sync                     src/sync.py      (orchestration)
    ├── MetaAdsClient.fetch_ad_insights   src/meta_client.py  (Graph API)
    └── NotionWriter.upsert_ad            src/notion_writer.py (Notion API)
```

---

## Setup

You'll do this once. Roughly: get a Meta token, create a Notion integration +
database, then store four secrets in GitHub.

### 1. Meta Marketing API access

You need an access token with the **`ads_read`** permission and your **ad
account id**.

1. Create an app at <https://developers.facebook.com/apps> (type: *Business*).
2. Add the **Marketing API** product.
3. Get a token:
   - Quick start / short-lived: use the **Graph API Explorer**, select your app,
     add the `ads_read` scope, and generate a token. Short-lived tokens expire in
     ~1–2 hours — fine for a first test, not for the scheduled job.
   - **Recommended for automation:** create a **System User** in
     [Business Settings](https://business.facebook.com/settings) → *System users*,
     assign it your ad account with `ads_read`, and generate a **long-lived
     token**. These don't expire on a fixed clock the way user tokens do.
4. Find your **ad account id** in Ads Manager (the `act_XXXXXXXXXX` in the URL, or
   Account Overview). You can store it with or without the `act_` prefix.

Verify your token works:

```bash
curl -G "https://graph.facebook.com/v21.0/act_<YOUR_ID>/insights" \
  --data-urlencode "fields=ad_name,spend" \
  --data-urlencode "level=ad" \
  --data-urlencode "date_preset=last_7d" \
  --data-urlencode "access_token=<YOUR_TOKEN>"
```

> If the API version in the URL is rejected as deprecated, bump it to the current
> version from the [changelog](https://developers.facebook.com/docs/graph-api/changelog)
> and set `META_API_VERSION` accordingly.

### 2. Notion integration + database

1. Create an internal integration at <https://www.notion.so/my-integrations>
   and copy its **Internal Integration Secret** (this is `NOTION_TOKEN`).
2. In Notion, open (or create) a page that will hold the metrics database, then
   **Share** that page with your integration (`•••` menu → *Connections* →
   your integration).
3. Get the **parent page id**: it's the 32-character hex string in the page URL
   (e.g. `https://www.notion.so/My-Page-`**`8a1b...c3`**).
4. Create the database automatically with the correct schema:

   ```bash
   pip install -r requirements.txt
   NOTION_TOKEN=secret_xxx python -m src.setup_notion <parent_page_id> "Meta Ads — Weekly Metrics"
   ```

   It prints a **database id** — that's your `NOTION_DATABASE_ID`. (Prefer to
   build it by hand? Create a database with the columns from the table above,
   matching the names and types in `src/schema.py`.)

### 3. Test locally (optional but recommended)

```bash
cp .env.example .env      # then fill in the four values
# Dry run first — prints a table, writes nothing to Notion:
DRY_RUN=true python -m src.sync
# Then a real run:
python -m src.sync
```

### 4. Wire up GitHub Actions

Add these four **repository secrets** under
*Settings → Secrets and variables → Actions → New repository secret*:

| Secret | Value |
| --- | --- |
| `META_ACCESS_TOKEN` | your long-lived Meta token |
| `META_AD_ACCOUNT_ID` | e.g. `act_1234567890` (or just `1234567890`) |
| `NOTION_TOKEN` | your Notion integration secret |
| `NOTION_DATABASE_ID` | the id printed by `setup_notion` |

Optionally add a repository **variable** `META_API_VERSION` (e.g. `v21.0`) to
override the Graph API version without touching code.

Then the workflow in [`.github/workflows/weekly-sync.yml`](.github/workflows/weekly-sync.yml)
runs every **Friday at 15:00 UTC**. Two important notes:

- **It must be on your default branch to run on schedule.** GitHub only fires
  scheduled workflows from the default branch. Merge this branch first.
- **Test it immediately without waiting for Friday:** go to the **Actions** tab →
  *Weekly Meta Ads → Notion Sync* → **Run workflow**. You can tick *dry run* and
  set a custom look-back for that manual run.

To change the schedule, edit the `cron` line (it's in **UTC**). For example
`0 21 * * 5` is Friday 9pm UTC. To change the time zone reference, adjust the
hour accordingly — cron has no time-zone field.

---

## Configuration reference

All configuration is via environment variables (see [`.env.example`](.env.example)):

| Variable | Required | Default | Purpose |
| --- | --- | --- | --- |
| `META_ACCESS_TOKEN` | ✅ | — | Meta token with `ads_read` |
| `META_AD_ACCOUNT_ID` | ✅ | — | Ad account, `act_` prefix optional |
| `META_API_VERSION` | — | `v21.0` | Graph API version |
| `NOTION_TOKEN` | ✅¹ | — | Notion integration secret |
| `NOTION_DATABASE_ID` | ✅¹ | — | Target database id |
| `LOOKBACK_DAYS` | — | `7` | Window length, ending yesterday |
| `MIN_SPEND` | — | `0` | Skip ads spending below this |
| `DRY_RUN` | — | `false` | Print instead of writing to Notion |

¹ Not required when `DRY_RUN=true`.

## Troubleshooting

- **`Configuration error: Missing required environment variable`** — a secret
  isn't set. Check the four secrets / your `.env`.
- **Meta `HTTP 400, code 190`** — the token is invalid or expired. Regenerate it
  (use a System User token for longevity).
- **Meta `code 17` / `613`** — you hit a rate limit; the client already retries
  with backoff, but very large accounts may need a narrower window.
- **Notion `HTTP 404` / `object not found`** — the database isn't shared with the
  integration, or `NOTION_DATABASE_ID` is wrong.
- **Notion `HTTP 400, ... is not a property that exists`** — the database columns
  don't match `src/schema.py`. Re-create it with `setup_notion`, or rename the
  columns to match.
- **No rows appear** — Meta only returns ads that had delivery in the window. If
  everything was paused all week, there's nothing to report.

## Development

```bash
pip install -r requirements.txt
python -m pytest        # runs the offline unit tests in tests/
```

The tests cover the metric parsing and the date-window logic and need no network
access or credentials.
