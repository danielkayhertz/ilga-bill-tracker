#!/usr/bin/env python3
"""Update bill status from ILGA.gov FTP XML files.

Run from ilga-bill-tracker/ directory:
    python scripts/update_bill_status.py

Or from anywhere — the script uses __file__ to find the repo root.

This script:
  - Processes any bills in the BILLS list (empty by default — add your own)
  - Refreshes ILGA fields for all user-added bills in user-bills.json
  - Tracks stageChangedAt (set when stage label changes vs. previous run)
  - Parses nextActionDate / nextActionType from ILGA XML <nextaction> element
"""

import json
import re
import sys
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

ILGA_FTP_BASE = "https://www.ilga.gov/ftp/legislation/104/BillStatus/XML/10400"

# Pre-loaded bills — add bill numbers here if you want to track a fixed set.
# Each entry must have at minimum: billNumber, title, year (list of ints),
# status ("Not passed into law" or "Passed into law"), category, url.
# ILGA fields (stage, primarySponsor, lastAction, etc.) are filled in automatically.
#
# Example:
#   {"billNumber": "HB1234", "title": "My Bill", "year": [2026],
#    "status": "Not passed into law", "category": "Housing",
#    "url": "https://www.ilga.gov/Legislation/BillStatus?DocNum=1234&GAID=18&DocTypeID=HB&SessionID=114"}
BILLS = []


def parse_bill_number(bill_number):
    """Parse 'HB3466' → ('HB', '3466')."""
    m = re.match(r'^([A-Z]+)(\d+)$', bill_number)
    if not m:
        raise ValueError(f"Cannot parse bill number: {bill_number}")
    return m.group(1), m.group(2)


def get_xml_url(bill_number):
    """Build ILGA FTP XML URL. DocNum is zero-padded to 4 digits."""
    doc_type, doc_num = parse_bill_number(bill_number)
    padded = doc_num.zfill(4)
    return f"{ILGA_FTP_BASE}{doc_type}{padded}.xml"


def fetch_xml(url):
    """Fetch URL; return bytes or None on error."""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "ilga-bill-tracker/1.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.read()
    except Exception as e:
        print(f"    WARNING: fetch failed for {url}: {e}", file=sys.stderr)
        return None


def get_last_action_fields(root):
    """Extract lastAction text and date from <lastaction> element."""
    la_el = root.find("lastaction")
    if la_el is None:
        return "", ""
    action_el = la_el.find("action")
    date_el   = la_el.find("statusdate")
    last_action      = (action_el.text or "").strip() if action_el is not None else ""
    last_action_date = (date_el.text   or "").strip() if date_el   is not None else ""
    return last_action, last_action_date


def get_primary_sponsor(root):
    """Extract the chief sponsor name from <sponsor><sponsors> text."""
    sponsor_el = root.find("sponsor")
    if sponsor_el is None:
        return ""
    sponsors_el = sponsor_el.find("sponsors")
    if sponsors_el is None or not sponsors_el.text:
        return ""
    first = re.split(r'-|,|\s+and\s+', sponsors_el.text.strip())[0].strip()
    return first


def get_action_texts(root):
    """Collect all <action> texts from the flat children of <actions>."""
    texts = []
    actions_el = root.find("actions")
    if actions_el is not None:
        for child in actions_el:
            if child.tag.lower() == "action" and child.text:
                texts.append(child.text.strip().lower())
    return texts


def get_next_action(root):
    """Parse next scheduled action from <nextaction> element.

    Returns (date_str, action_type_str) — both empty strings if not found.
    """
    na = root.find("nextaction")
    if na is not None:
        date_el   = na.find("statusdate")
        action_el = na.find("action")
        if date_el is not None and date_el.text:
            date_str   = date_el.text.strip()
            action_str = (action_el.text or "").strip() if action_el is not None else ""
            return date_str, action_str
    return "", ""


def map_stage(last_action, action_history, doc_type):
    """Map last action + action history to a stage label."""
    la = last_action.lower()

    if "approved by governor" in la or "public act" in la:
        return "Signed into Law"
    if "sent to the governor" in la or "to the governor" in la:
        return "Awaiting Governor Signature"
    if "passed both" in la or "enrolled" in la:
        return "Enrolled"
    if "passed senate" in la:
        return "Passed Senate"
    if "passed house" in la:
        return "Passed House"
    if any(k in la for k in ["vetoed", "failed", "did not pass", "tabled", "withdrawn"]):
        return "Failed"

    history = " ".join(action_history)
    if "passed house" in history or "arrive in senate" in history:
        return "In Senate Committee"
    elif "passed senate" in history or "arrive in house" in history:
        return "In House Committee"
    else:
        return "In House Committee" if doc_type == "HB" else "In Senate Committee"


def _ilga_fields_from_xml(xml_bytes, bill_number, prev_stage, prev_stage_changed_at, fetched_at):
    """Parse XML bytes and return the computed ILGA fields dict.

    Returns None if XML parsing fails, signalling the caller to use fallback values.
    """
    doc_type, _ = parse_bill_number(bill_number)
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError as e:
        print(f"    WARNING: XML parse error for {bill_number}: {e}", file=sys.stderr)
        return None

    last_action, last_action_date = get_last_action_fields(root)
    action_history  = get_action_texts(root)
    primary_sponsor = get_primary_sponsor(root)
    new_stage       = map_stage(last_action, action_history, doc_type)
    next_action_date, next_action_type = get_next_action(root)

    # stageChangedAt: update only if stage has changed
    if new_stage != prev_stage:
        stage_changed_at = fetched_at
    else:
        stage_changed_at = prev_stage_changed_at or fetched_at

    print(f"    stage={new_stage}  sponsor={primary_sponsor}  lastAction={last_action[:60]}")

    return {
        "stage":          new_stage,
        "primarySponsor": primary_sponsor,
        "lastAction":     last_action,
        "lastActionDate": last_action_date,
        "ilgaFetchedAt":  fetched_at,
        "stageChangedAt": stage_changed_at,
        "nextActionDate": next_action_date or None,
        "nextActionType": next_action_type or None,
    }


def process_bill(bill, prev_data):
    """Fetch ILGA XML and return updated bill dict. Falls back to previous data on error."""
    bill_number = bill["billNumber"]
    url = get_xml_url(bill_number)
    print(f"  {bill_number} -> {url}")

    prev         = prev_data.get(bill_number, {})
    fetched_at   = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    prev_stage   = prev.get("stage")
    prev_sca     = prev.get("stageChangedAt")

    xml_bytes = fetch_xml(url)
    if xml_bytes is None:
        return {
            **bill,
            "stage":          prev.get("stage",          "Unknown"),
            "primarySponsor": prev.get("primarySponsor", ""),
            "lastAction":     prev.get("lastAction",     ""),
            "lastActionDate": prev.get("lastActionDate", ""),
            "ilgaFetchedAt":  prev.get("ilgaFetchedAt",  ""),
            "stageChangedAt": prev.get("stageChangedAt", ""),
            "nextActionDate": prev.get("nextActionDate"),
            "nextActionType": prev.get("nextActionType"),
        }

    fields = _ilga_fields_from_xml(xml_bytes, bill_number, prev_stage, prev_sca, fetched_at)
    if fields is None:
        return {
            **bill,
            "stage":          prev.get("stage",          "Unknown"),
            "primarySponsor": prev.get("primarySponsor", ""),
            "lastAction":     prev.get("lastAction",     ""),
            "lastActionDate": prev.get("lastActionDate", ""),
            "ilgaFetchedAt":  prev.get("ilgaFetchedAt",  ""),
            "stageChangedAt": prev.get("stageChangedAt", ""),
            "nextActionDate": prev.get("nextActionDate"),
            "nextActionType": prev.get("nextActionType"),
        }

    return {**bill, **fields}


def process_user_bill(bill, fetched_at):
    """Refresh ILGA fields for a user-added bill, preserving user-set fields.

    Preserves: title, description, category, userAdded, id, year, status, url.
    Updates: stage, primarySponsor, lastAction, lastActionDate, ilgaFetchedAt,
             stageChangedAt, nextActionDate, nextActionType.
    """
    bill_number = bill["billNumber"]
    url = get_xml_url(bill_number)
    print(f"  [user] {bill_number} -> {url}")

    prev_stage = bill.get("stage")
    prev_sca   = bill.get("stageChangedAt")

    xml_bytes = fetch_xml(url)
    if xml_bytes is None:
        return bill  # keep existing values

    fields = _ilga_fields_from_xml(xml_bytes, bill_number, prev_stage, prev_sca, fetched_at)
    if fields is None:
        return bill

    # Merge: start from bill (preserves user fields), overlay with ILGA fields
    return {**bill, **fields}


def load_previous_data(output_path):
    """Load previous bills.json to preserve data on individual fetch failures."""
    if not output_path.exists():
        return {}
    try:
        with open(output_path, encoding="utf-8") as f:
            data = json.load(f)
        return {b["billNumber"]: b for b in data}
    except Exception:
        return {}


def load_user_bills(user_bills_path):
    """Load user-bills.json; returns empty list if missing or invalid."""
    if not user_bills_path.exists():
        return []
    try:
        with open(user_bills_path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def main():
    repo_root       = Path(__file__).parent.parent
    output_path     = repo_root / "data" / "bills.json"
    user_bills_path = repo_root / "data" / "user-bills.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)

    prev_data = load_previous_data(output_path)

    results = []
    changed = 0

    if BILLS:
        print(f"Updating {len(BILLS)} base bills -> {output_path}\n")
        for bill in BILLS:
            result = process_bill(bill, prev_data)
            results.append(result)
            prev = prev_data.get(bill["billNumber"], {})
            if result.get("stage") != prev.get("stage") or result.get("lastAction") != prev.get("lastAction"):
                changed += 1

        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(results, f, indent=2, ensure_ascii=False)

        print(f"\nDone. {changed} bill(s) changed. Written to {output_path}")
    else:
        print("No base bills configured in BILLS — skipping bills.json update.")
        print("Add bill entries to the BILLS list in this script to pre-load bills.")

    # ── Refresh user-added bills ──────────────────────────────────────────────
    user_bills = load_user_bills(user_bills_path)
    if user_bills:
        print(f"\nRefreshing {len(user_bills)} user-added bill(s) -> {user_bills_path}")
        fetched_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        updated = [process_user_bill(b, fetched_at) for b in user_bills]
        with open(user_bills_path, "w", encoding="utf-8") as f:
            json.dump(updated, f, indent=2, ensure_ascii=False)
        print(f"Done. Refreshed {len(updated)} user-added bill(s).")
    else:
        print("\nNo user-added bills to refresh.")


if __name__ == "__main__":
    main()
