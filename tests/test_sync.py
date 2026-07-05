"""Offline unit tests. No network or credentials required.

Run with:  python -m pytest
"""

import os

from src.csv_parser import parse_meta_csv, _infer_type, _to_date, _to_float
from src.schema import notion_property_spec, notion_property_value

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "sample_export.csv")


# --- Parsing the real-world export shape ------------------------------------

def test_parse_skips_account_total_and_blank():
    export = parse_meta_csv(FIXTURE)
    # 5 data rows minus the account-total row (blank ad name) = 4 ads.
    assert len(export.rows) == 4
    assert export.skipped == 1
    # "SVSC 2026 Ad" is renamed to "Leo talking ad" (see customizations.py).
    assert {r["title"] for r in export.rows} == {
        "Leo talking ad",
        "Advisor talking ad",
        "Hype Video",
        "Highschool checklist post",
    }


def test_ad_rename_applied():
    export = parse_meta_csv(FIXTURE)
    titles = {r["title"] for r in export.rows}
    assert "Leo talking ad" in titles
    assert "SVSC 2026 Ad" not in titles


def test_ignored_column_excluded():
    export = parse_meta_csv(FIXTURE)
    names = {c.name for c in export.columns}
    # "Attribution setting" is in IGNORED_COLUMNS and must never be synced.
    assert "Attribution setting" not in names
    for row in export.rows:
        assert "Attribution setting" not in row["fields"]


def test_reporting_window_mapped():
    export = parse_meta_csv(FIXTURE)
    assert export.has_week_start and export.has_week_ending
    row = export.rows[0]
    assert row["week_start"] == "2026-06-28"
    assert row["week_ending"] == "2026-07-04"


def test_numeric_and_text_columns_inferred():
    export = parse_meta_csv(FIXTURE)
    by_name = {c.name: c for c in export.columns}
    # Numbers
    assert by_name["Impressions"].ntype == "number"
    assert by_name["Reach"].ntype == "number"
    assert by_name["Frequency"].ntype == "number"
    # Cost-like -> dollar format
    assert by_name["Amount Spent"].ntype == "number"
    assert by_name["Amount Spent"].number_format == "dollar"
    assert by_name["CPC (cost per link click)"].number_format == "dollar"
    # Non-cost number -> plain
    assert by_name["Impressions"].number_format == "number"
    # Text
    assert by_name["Currency"].ntype == "rich_text"


def test_amount_spent_header_normalised_and_valued():
    export = parse_meta_csv(FIXTURE)
    svsc = next(r for r in export.rows if r["title"] == "Leo talking ad")
    ntype, value = svsc["fields"]["Amount Spent"]
    assert ntype == "number"
    assert value == 195.8


def test_reporting_columns_not_duplicated_as_generic():
    export = parse_meta_csv(FIXTURE)
    names = {c.name for c in export.columns}
    assert "Reporting starts" not in names
    assert "Reporting ends" not in names
    assert "Ad name" not in names  # consumed as the title


# --- Future-proofing: brand-new columns just work ---------------------------

def test_new_columns_are_picked_up(tmp_path):
    csv = tmp_path / "next_week.csv"
    csv.write_text(
        '"Ad name","Amount spent (USD)","Purchases","Purchase ROAS","Reporting starts","Reporting ends"\n'
        '"New Creative","50.5","4","3.2","2026-07-05","2026-07-11"\n'
    )
    export = parse_meta_csv(str(csv))
    by_name = {c.name: c for c in export.columns}
    assert set(by_name) == {"Amount Spent", "Purchases", "Purchase ROAS"}
    assert by_name["Purchases"].ntype == "number"
    # "Purchase ROAS" is numeric but has no cost keyword -> plain number format.
    assert by_name["Purchase ROAS"].ntype == "number"
    assert by_name["Purchase ROAS"].number_format == "number"
    row = export.rows[0]
    assert row["fields"]["Purchases"] == ("number", 4.0)


# --- Type / value helpers ---------------------------------------------------

def test_infer_type():
    assert _infer_type("impressions", ["1", "2", "3"]) == ("number", "number")
    assert _infer_type("amount spent (usd)", ["1.5", "2"]) == ("number", "dollar")
    assert _infer_type("reporting starts", ["2026-01-01"]) == ("date", None)
    assert _infer_type("currency", ["USD", "USD"]) == ("rich_text", None)
    assert _infer_type("empty col", []) == ("rich_text", None)


def test_to_float_handles_commas_and_symbols():
    assert _to_float("1,660") == 1660.0
    assert _to_float("$195.80") == 195.8
    assert _to_float("2.25%") == 2.25
    assert _to_float("") is None
    assert _to_float("n/a") is None


def test_to_date_formats():
    assert _to_date("2026-07-04") == "2026-07-04"
    assert _to_date("07/04/2026") == "2026-07-04"
    assert _to_date("") is None


def test_notion_property_spec():
    assert notion_property_spec("title") == {"title": {}}
    assert notion_property_spec("number", "dollar") == {"number": {"format": "dollar"}}
    assert notion_property_spec("number") == {"number": {"format": "number"}}
    assert notion_property_spec("date") == {"date": {}}


def test_notion_property_value():
    assert notion_property_value("number", 12.5) == {"number": 12.5}
    assert notion_property_value("date", "2026-07-04") == {"date": {"start": "2026-07-04"}}
    assert notion_property_value("date", None) == {"date": None}
    assert notion_property_value("title", "")["title"][0]["text"]["content"] == "(unnamed ad)"
    assert notion_property_value("rich_text", None)["rich_text"][0]["text"]["content"] == ""
