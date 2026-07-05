"""Personal customizations for the sync — safe to edit freely.

These are applied every time a CSV is parsed, so changes here take effect on the
next sync without touching any other code.
"""

# Columns to never send to Notion. Matched case-insensitively against the CSV
# header, so "Attribution setting" also matches "attribution setting", etc.
# The sync will not create these columns, and any values in them are dropped.
IGNORED_COLUMNS = [
    "Attribution setting",
    "Currency",
]

# Rename ads on the way in: {name as it appears in the CSV: name to use in Notion}.
# Matched case-insensitively on the CSV name. The renamed value is what gets
# written and what rows are de-duplicated on, so a rename is stable week to week.
AD_RENAMES = {
    "SVSC 2026 Ad": "Leo talking ad",
}

# Whether to include the reporting window (Week Start / Week Ending) columns.
# When False, those columns are never created, and each row is instead
# identified by its ad name + "Synced On" date (the day the sync runs). Set this
# back to True to bring the Week Start / Week Ending columns back.
SYNC_REPORTING_WINDOW = False

