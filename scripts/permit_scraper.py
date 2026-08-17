#!/usr/bin/env python3
"""
Titan Permit Scraper
Runs daily — pulls Cedar Rapids (+ Iowa City) roofing/siding permits,
scores them, and pushes new ones to Supabase.

Setup on mini PC:
  pip install requests openpyxl supabase python-dotenv
  Add to crontab: 0 6 * * * /usr/bin/python3 /path/to/permit_scraper.py >> /var/log/titan_permits.log 2>&1
"""

import os
import io
import re
import json
import datetime
import requests
import openpyxl
from dotenv import load_dotenv

load_dotenv()

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_SERVICE_KEY"]

HEADERS = {"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}",
           "Content-Type": "application/json", "Prefer": "resolution=ignore-duplicates,return=minimal"}

# Keywords that indicate roofing/siding/storm-related permits
ROOF_KEYWORDS = [
    "roof", "re-roof", "reroof", "shingle", "siding", "fascia",
    "soffit", "gutter", "storm", "hail", "wind", "exterior",
    "cladding", "flashing"
]

# Cedar Rapids monthly Excel URLs
# Pattern: https://www.cedar-rapids.org/Building Services/Monthly Permit Reports/{YEAR}/{N} {Month}.xls
CR_BASE = "https://www.cedar-rapids.org/Building%20Services/Monthly%20Permit%20Reports"
MONTHS = ["January","February","March","April","May","June",
          "July","August","September","October","November","December"]


def is_roofing_permit(row_values: list) -> bool:
    text = " ".join(str(v) for v in row_values if v).lower()
    return any(kw in text for kw in ROOF_KEYWORDS)


def score_permit(permit: dict) -> int:
    score = 50
    desc = (permit.get("description") or "").lower()
    ptype = (permit.get("permit_type") or "").lower()

    # Roofing scores higher than siding
    if any(k in desc + ptype for k in ["roof", "re-roof", "reroof", "shingle"]):
        score += 25
    if any(k in desc + ptype for k in ["storm", "hail", "wind"]):
        score += 20
    if any(k in desc + ptype for k in ["siding", "exterior"]):
        score += 10

    # Higher job value = higher score
    val = permit.get("value") or 0
    if val > 20000:
        score += 15
    elif val > 10000:
        score += 8
    elif val > 5000:
        score += 3

    return min(score, 99)


def get_cr_url_for_month(year: int, month: int) -> str:
    month_name = MONTHS[month - 1]
    return f"{CR_BASE}/{year}/{month}%20{month_name}.xls"


def fetch_excel(url: str) -> bytes | None:
    try:
        r = requests.get(url, timeout=30, allow_redirects=True,
                         headers={"User-Agent": "TitanContractingOS/1.0"})
        if r.status_code == 200 and len(r.content) > 1000:
            return r.content
        # try .xlsx variant
        xlsx_url = url.replace(".xls", ".xlsx")
        r2 = requests.get(xlsx_url, timeout=30, allow_redirects=True,
                          headers={"User-Agent": "TitanContractingOS/1.0"})
        if r2.status_code == 200 and len(r2.content) > 1000:
            return r2.content
        return None
    except Exception as e:
        print(f"fetch error {url}: {e}")
        return None


def parse_cedar_rapids(content: bytes, year: int, month: int) -> list[dict]:
    """Parse Cedar Rapids monthly permit Excel and return roofing permits."""
    try:
        wb = openpyxl.load_workbook(io.BytesIO(content), read_only=True, data_only=True)
        ws = wb.active
        rows = list(ws.iter_rows(values_only=True))
        wb.close()
    except Exception as e:
        print(f"parse error: {e}")
        return []

    if not rows:
        return []

    # Find header row (first row with more than 3 non-empty cells)
    header_row = 0
    headers = []
    for i, row in enumerate(rows[:10]):
        non_empty = [str(v).strip() for v in row if v is not None]
        if len(non_empty) >= 3:
            headers = [str(v).strip().lower() if v else "" for v in row]
            header_row = i
            break

    if not headers:
        print("could not find header row")
        return []

    print(f"  headers: {headers}")

    # Map column names to indices (flexible matching)
    def col(names):
        for name in names:
            for i, h in enumerate(headers):
                if name in h:
                    return i
        return None

    idx_num    = col(["permit no", "permit num", "number", "permit #", "no."])
    idx_addr   = col(["address", "location", "site"])
    idx_type   = col(["type", "permit type", "work type", "category"])
    idx_desc   = col(["description", "desc", "work desc", "scope"])
    idx_val    = col(["value", "valuation", "job value", "estimated"])
    idx_cont   = col(["contractor", "company", "applicant"])
    idx_owner  = col(["owner", "property owner"])
    idx_date   = col(["issue", "issued", "date", "permit date"])

    permits = []
    for row in rows[header_row + 1:]:
        if not any(row):
            continue

        vals = [v for v in row]

        if not is_roofing_permit(vals):
            continue

        def get(idx):
            if idx is None or idx >= len(vals):
                return None
            v = vals[idx]
            return str(v).strip() if v is not None else None

        # Parse value
        raw_val = get(idx_val)
        value = None
        if raw_val:
            clean = re.sub(r"[^\d.]", "", raw_val)
            try:
                value = float(clean)
            except Exception:
                pass

        # Parse date
        raw_date = get(idx_date)
        issued_date = None
        if raw_date:
            try:
                if isinstance(vals[idx_date], datetime.datetime):
                    issued_date = vals[idx_date].date().isoformat()
                else:
                    # try common formats
                    for fmt in ["%m/%d/%Y", "%Y-%m-%d", "%m-%d-%Y", "%m/%d/%y"]:
                        try:
                            issued_date = datetime.datetime.strptime(raw_date, fmt).date().isoformat()
                            break
                        except Exception:
                            pass
            except Exception:
                pass

        if not issued_date:
            # default to current month
            issued_date = datetime.date(year, month, 1).isoformat()

        permit = {
            "permit_number": get(idx_num) or f"CR-{year}{month:02d}-{len(permits)}",
            "address": get(idx_addr),
            "city": "Cedar Rapids",
            "state": "IA",
            "permit_type": get(idx_type),
            "description": get(idx_desc),
            "contractor": get(idx_cont),
            "owner": get(idx_owner),
            "value": value,
            "issued_date": issued_date,
            "source": "cedar_rapids_city",
        }
        permit["score"] = score_permit(permit)
        permits.append(permit)

    return permits


def push_to_supabase(permits: list[dict]) -> int:
    if not permits:
        return 0

    # Batch insert, ignore duplicates on permit_number
    r = requests.post(
        f"{SUPABASE_URL}/rest/v1/permits",
        headers=HEADERS,
        data=json.dumps(permits),
        timeout=30
    )
    if r.status_code in (200, 201):
        print(f"  pushed {len(permits)} permits")
        return len(permits)
    else:
        print(f"  supabase error {r.status_code}: {r.text[:200]}")
        return 0


def run():
    today = datetime.date.today()
    year, month = today.year, today.month

    print(f"[{today}] Titan Permit Scraper starting...")

    # Try current month, fall back to previous if current isn't posted yet
    for (y, m) in [(year, month), (year, month - 1 if month > 1 else 12)]:
        y = year if m > 0 else year - 1
        url = get_cr_url_for_month(y, m)
        print(f"  Fetching Cedar Rapids {MONTHS[m-1]} {y}...")
        content = fetch_excel(url)
        if content:
            permits = parse_cedar_rapids(content, y, m)
            print(f"  Found {len(permits)} roofing/siding permits")
            pushed = push_to_supabase(permits)
            print(f"  New permits added: {pushed}")
            break
        else:
            print(f"  No file found for {MONTHS[m-1]} {y}, trying previous month...")

    print("Done.")


if __name__ == "__main__":
    run()
