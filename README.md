# Meta Ads CSV → Notion

Turn a **Meta Ads Manager CSV export** into rows in a **Notion database** — one
row per ad, per reporting week. You export the CSV from Ads Manager (no Meta API,
no app, no access token), hand it to the script, and it writes the numbers into
Notion.

**Schema-adaptive:** you can change which columns you export from week to week.
The parser reads whatever columns are in the CSV, figures out each one's type
(number / date / text), and **any column that doesn't exist in your Notion
database yet is created automatically** on the next sync. New metric next week
(Purchases, ROAS, video views, …)? It just shows up as a new Notion column.

Re-running the same export is safe: rows are keyed on _(ad name, reporting
window)_, so a re-upload **updates** the existing rows instead of duplicating.

## How it works

```
Ads Manager  --export CSV-->  python -m src.sync export.csv
                                   │
                     src/csv_parser.py   parse + infer column types, skip the
                                         account-total row
                                   │
                     src/notion_writer.py  add any missing columns to the DB,
                                           then upsert one row per ad
                                   ▼
                              Notion database
```

Fixed columns always present: **Ad Name** (title), **Week Start**, **Week
Ending** (from the export's reporting dates), and **Synced On** (when it ran).
Everything else mirrors your export.

---

## One-time setup

### 1. Create a Notion integration

1. Go to <https://www.notion.so/my-integrations> → **New integration** →
   copy the **Internal Integration Secret**. That's your `NOTION_TOKEN`.

### 2. Create the database

1. In Notion, open (or make) a page to hold the database, then **Share** it
   with your integration (`•••` → *Connections* → your integration).
2. Copy that page's id — the 32-char hex string in its URL.
3. Create the database with the correct starting columns:

   ```bash
   pip install -r requirements.txt
   NOTION_TOKEN=secret_xxx python -m src.setup_notion <parent_page_id> "Meta Ads — Weekly Metrics"
   ```

   It prints a **database id** — that's your `NOTION_DATABASE_ID`.

   > Prefer an existing database? Just share it with the integration and use its
   > id. The sync will add any missing columns itself; it only needs the title
   > column to exist (every Notion database has one).

### 3. Store your two secrets

```bash
cp .env.example .env     # then fill in NOTION_TOKEN and NOTION_DATABASE_ID
```

---

## Weekly workflow

### 1. Export the CSV from Ads Manager

- Ads Manager → **Reports** (or the **Ads** tab) → set the **date range** to the
  week you want, pick your columns, and **Export → CSV**.
- Any columns work. Tip: set a **weekly** date range (e.g. the last 7 days) so
  each export is a distinct week — the reporting dates in the file become the
  `Week Start` / `Week Ending` used to key the rows.

### 2. Sync it

```bash
# Preview first — prints a table, writes nothing:
DRY_RUN=true python -m src.sync path/to/export.csv

# Then the real thing:
python -m src.sync path/to/export.csv
```

That's it. The account-total row (blank ad name) is skipped automatically.

### Two ways to run it every Friday

- **You run it** locally with the command above.
- **Hand the CSV to Claude Code and ask it to sync** — with `NOTION_TOKEN` and
  `NOTION_DATABASE_ID` available in the environment, it runs the same command
  for you. See "Running it with Claude" below.

---

## Running it with Claude

If you'd rather just drop the file in a chat each week and say "update Notion":

1. Set `NOTION_TOKEN` and `NOTION_DATABASE_ID` as **environment variables /
   secrets** in your Claude Code environment (so they persist between sessions).
2. Each Friday: upload the CSV export and ask Claude to run the sync. It will
   execute `python -m src.sync <your-file>` and report what it created/updated.

(Optional) Claude can also set a **recurring Friday reminder** so you don't
forget to export and send the file.

---

## Configuration reference

| Variable | Required | Default | Purpose |
| --- | --- | --- | --- |
| `NOTION_TOKEN` | ✅¹ | — | Notion integration secret |
| `NOTION_DATABASE_ID` | ✅¹ | — | Target database id |
| `CSV_PATH` | — | — | CSV path (alternative to the CLI argument) |
| `MIN_SPEND` | — | `0` | Skip ads spending below this (needs a spend column) |
| `DRY_RUN` | — | `false` | Print the parsed metrics instead of writing |

¹ Not required when `DRY_RUN=true`.

## Notes & troubleshooting

- **Which row is the ad name?** The parser looks for an `Ad name` column (and
  falls back to `Ad set name` / `Campaign name` / `Account name`). That column
  becomes the row title.
- **Column types** are inferred from the data: all-numeric → number (dollar
  format for cost-like columns such as *Amount spent*, *CPC*, *CPM*), all-date →
  date, otherwise text.
- **No reporting dates in the export?** Rows are then keyed on _(ad name, sync
  date)_, so a same-day re-run updates and a different day creates new rows. For
  clean weekly history, keep the reporting-date columns in your export.
- **Notion `404` / object not found** — the database isn't shared with the
  integration, or `NOTION_DATABASE_ID` is wrong.
- **A column didn't appear in Notion** — check the integration has *Update
  content* capability (internal integrations do by default); the sync needs it to
  add columns.

## Development

```bash
pip install -r requirements.txt
python -m pytest        # offline tests: parsing, type inference, Notion payloads
```

The tests use `tests/fixtures/sample_export.csv`, which matches a real Ads
Manager export, and need no network access or credentials.
