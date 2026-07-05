"""Single source of truth for the Notion database schema.

Both ``setup_notion.py`` (which creates the database) and ``notion_writer.py``
(which writes rows into it) build their payloads from ``PROPERTIES`` so the two
can never drift apart. If you want to rename a column or change a number
format, do it here once.

Each entry is ``(metric_key, notion_property_name, notion_type, number_format)``
where ``metric_key`` matches the keys produced by ``meta_client.parse_row`` (plus
``week_ending`` / ``report_date`` which the sync adds), and ``number_format`` is
only meaningful for ``number`` properties.
"""

# The metric key that becomes the row's title (every Notion DB needs exactly one
# title property). We use the ad name.
TITLE_KEY = "ad_name"

# (metric_key, notion_name, notion_type, number_format)
PROPERTIES = [
    ("ad_name",        "Ad Name",        "title",     None),
    ("ad_id",          "Ad ID",          "rich_text", None),
    ("campaign_name",  "Campaign",       "rich_text", None),
    ("adset_name",     "Ad Set",         "rich_text", None),
    ("week_ending",    "Week Ending",    "date",      None),
    ("report_date",    "Report Date",    "date",      None),
    ("spend",          "Spend",          "number",    "dollar"),
    ("impressions",    "Impressions",    "number",    "number"),
    ("reach",          "Reach",          "number",    "number"),
    ("clicks",         "Clicks",         "number",    "number"),
    ("ctr",            "CTR (%)",        "number",    "number"),
    ("cpc",            "CPC",            "number",    "dollar"),
    ("cpm",            "CPM",            "number",    "dollar"),
    ("frequency",      "Frequency",      "number",    "number"),
    ("purchases",      "Purchases",      "number",    "number"),
    ("purchase_value", "Purchase Value", "number",    "dollar"),
    ("roas",           "ROAS",           "number",    "number"),
]

# Property used together with "Week Ending" to detect an already-synced row so
# re-runs update in place instead of creating duplicates.
DEDUPE_ID_PROP = "Ad ID"
WEEK_PROP = "Week Ending"
