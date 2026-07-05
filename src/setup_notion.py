"""One-time helper: create the Notion database with the correct schema.

Usage:
    # Share a Notion *page* with your integration first, then:
    NOTION_TOKEN=... python -m src.setup_notion <parent_page_id> ["Database title"]

    # or pass the parent page id via env:
    NOTION_TOKEN=... NOTION_PARENT_PAGE_ID=... python -m src.setup_notion

It prints the new database id. Put that value into NOTION_DATABASE_ID (locally in
.env, and as a GitHub Actions secret) so the weekly sync knows where to write.

You only need to run this once. If you'd rather build the database by hand, the
required columns are listed in the README.
"""

from __future__ import annotations

import os
import sys

import requests

from .schema import PROPERTIES

NOTION_BASE = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"


def _schema_property(ntype: str, number_format: str | None) -> dict:
    if ntype == "title":
        return {"title": {}}
    if ntype == "rich_text":
        return {"rich_text": {}}
    if ntype == "date":
        return {"date": {}}
    if ntype == "number":
        return {"number": {"format": number_format or "number"}}
    raise ValueError(f"Unsupported property type: {ntype}")


def build_schema() -> dict:
    return {
        name: _schema_property(ntype, number_format)
        for _key, name, ntype, number_format in PROPERTIES
    }


def create_database(token: str, parent_page_id: str, title: str) -> dict:
    headers = {
        "Authorization": f"Bearer {token}",
        "Notion-Version": NOTION_VERSION,
        "Content-Type": "application/json",
    }
    body = {
        "parent": {"type": "page_id", "page_id": parent_page_id},
        "title": [{"type": "text", "text": {"content": title}}],
        "properties": build_schema(),
    }
    resp = requests.post(f"{NOTION_BASE}/databases", headers=headers, json=body, timeout=60)
    if resp.status_code >= 300:
        try:
            message = resp.json().get("message", resp.text)
        except ValueError:
            message = resp.text
        raise SystemExit(
            f"Failed to create database (HTTP {resp.status_code}): {message}\n"
            f"Make sure the integration is shared with the parent page and the "
            f"page id is correct."
        )
    return resp.json()


def main() -> int:
    token = os.environ.get("NOTION_TOKEN")
    if not token:
        raise SystemExit("Set NOTION_TOKEN (see https://www.notion.so/my-integrations).")

    parent_page_id = (
        sys.argv[1] if len(sys.argv) > 1 else os.environ.get("NOTION_PARENT_PAGE_ID")
    )
    if not parent_page_id:
        raise SystemExit(
            "Provide the parent page id as the first argument or via "
            "NOTION_PARENT_PAGE_ID. Share that page with your integration first."
        )

    title = sys.argv[2] if len(sys.argv) > 2 else "Meta Ads — Weekly Metrics"

    db = create_database(token, parent_page_id, title)
    db_id = db["id"]
    url = db.get("url", "")
    print("\n✅ Database created.")
    print(f"   Title:        {title}")
    print(f"   Database id:  {db_id}")
    if url:
        print(f"   URL:          {url}")
    print("\nNext: set this as NOTION_DATABASE_ID (in .env and as a GitHub secret):")
    print(f"   NOTION_DATABASE_ID={db_id}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
