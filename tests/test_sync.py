"""Offline unit tests. No network or credentials required.

Run with:  python -m pytest
"""

from datetime import date

from src.meta_client import MetaAdsClient
from src.notion_writer import _notion_value
from src.setup_notion import build_schema
from src.sync import compute_window


# --- Meta insight parsing ---------------------------------------------------

SAMPLE_ROW = {
    "ad_id": "123",
    "ad_name": "Summer Sale — Video A",
    "campaign_name": "Summer 2026",
    "adset_name": "US / 25-44",
    "spend": "150.75",
    "impressions": "20000",
    "reach": "15000",
    "clicks": "450",
    "ctr": "2.25",
    "cpc": "0.335",
    "cpm": "7.54",
    "frequency": "1.33",
    "actions": [
        {"action_type": "link_click", "value": "450"},
        {"action_type": "purchase", "value": "12"},
        {"action_type": "omni_purchase", "value": "14"},
    ],
    "action_values": [
        {"action_type": "purchase", "value": "600"},
        {"action_type": "omni_purchase", "value": "700"},
    ],
    "purchase_roas": [{"action_type": "omni_purchase", "value": "4.64"}],
}


def test_parse_row_core_metrics():
    parsed = MetaAdsClient.parse_row(SAMPLE_ROW)
    assert parsed["ad_id"] == "123"
    assert parsed["ad_name"] == "Summer Sale — Video A"
    assert parsed["spend"] == 150.75
    assert parsed["impressions"] == 20000
    assert parsed["clicks"] == 450
    assert parsed["ctr"] == 2.25


def test_parse_row_prefers_omni_purchase_no_double_count():
    parsed = MetaAdsClient.parse_row(SAMPLE_ROW)
    # omni_purchase has priority over purchase; we must not sum them.
    assert parsed["purchases"] == 14
    assert parsed["purchase_value"] == 700.0
    assert parsed["roas"] == 4.64


def test_parse_row_roas_fallback_when_missing():
    row = dict(SAMPLE_ROW)
    row.pop("purchase_roas")
    parsed = MetaAdsClient.parse_row(row)
    # 700 / 150.75 ≈ 4.6435
    assert abs(parsed["roas"] - (700 / 150.75)) < 1e-3


def test_parse_row_handles_missing_and_empty_fields():
    parsed = MetaAdsClient.parse_row({"ad_id": "9"})
    assert parsed["ad_name"] == "9"  # falls back to id
    assert parsed["spend"] == 0.0
    assert parsed["purchases"] == 0
    assert parsed["roas"] == 0.0


# --- Reporting window -------------------------------------------------------

def test_compute_window_ends_yesterday():
    since, until = compute_window(7, today=date(2026, 7, 3))  # a Friday
    assert until == "2026-07-02"
    assert since == "2026-06-26"


def test_compute_window_respects_lookback():
    since, until = compute_window(1, today=date(2026, 7, 3))
    assert since == until == "2026-07-02"


# --- Notion value construction ---------------------------------------------

def test_notion_value_types():
    assert _notion_value("number", 12.5) == {"number": 12.5}
    assert _notion_value("date", "2026-07-02") == {"date": {"start": "2026-07-02"}}
    assert _notion_value("date", None) == {"date": None}
    title = _notion_value("title", "Ad X")
    assert title["title"][0]["text"]["content"] == "Ad X"
    rich = _notion_value("rich_text", None)
    assert rich["rich_text"][0]["text"]["content"] == ""


def test_notion_value_title_never_empty():
    title = _notion_value("title", "")
    assert title["title"][0]["text"]["content"] == "(unnamed ad)"


# --- Schema stays consistent ------------------------------------------------

def test_build_schema_has_exactly_one_title():
    schema = build_schema()
    titles = [name for name, spec in schema.items() if "title" in spec]
    assert titles == ["Ad Name"]


def test_build_schema_number_formats():
    schema = build_schema()
    assert schema["Spend"] == {"number": {"format": "dollar"}}
    assert schema["CTR (%)"] == {"number": {"format": "number"}}
