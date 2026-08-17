#!/usr/bin/env python3
"""
Rolls up permits + storm_events by zip code into a neighborhoods table --
a canvassing-priority view rather than a per-lead one.
"""
import json
import os
import re
from datetime import datetime, timedelta, timezone

import requests
from dotenv import load_dotenv

load_dotenv("C:/titan/.env")
SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_SERVICE_KEY"]
READ_HEADERS = {"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}"}
WRITE_HEADERS = {**READ_HEADERS, "Content-Type": "application/json", "Prefer": "resolution=merge-duplicates,return=minimal"}

ZIP_RE = re.compile(r"(\d{5})\s*$")
CITY_ZIP_RE = re.compile(r"^(.*?),\s*([A-Z]{2})\s*(\d{5})\s*$")

TABLE_SQL = """CREATE TABLE IF NOT EXISTS public.neighborhoods (
  id uuid DEFAULT gen_random_uuid() PRIMARY KEY,
  zip_code text UNIQUE,
  city text,
  state text DEFAULT 'IA',
  permit_count_30d int DEFAULT 0,
  permit_count_90d int DEFAULT 0,
  avg_job_value float DEFAULT 0,
  storm_events_30d int DEFAULT 0,
  last_storm_at timestamptz,
  neighborhood_score int DEFAULT 0,
  signal text,
  updated_at timestamptz DEFAULT now()
);
ALTER TABLE public.neighborhoods ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Service role full access" ON public.neighborhoods USING (true) WITH CHECK (true);"""


def table_exists(name):
    r = requests.get(f"{SUPABASE_URL}/rest/v1/{name}?limit=1", headers=READ_HEADERS, timeout=15)
    return r.status_code == 200


def fetch_all(table, select="*"):
    rows, offset, page = [], 0, 1000
    while True:
        r = requests.get(
            f"{SUPABASE_URL}/rest/v1/{table}",
            headers={**READ_HEADERS, "Range": f"{offset}-{offset + page - 1}"},
            params={"select": select},
            timeout=30,
        )
        r.raise_for_status()
        batch = r.json()
        rows.extend(batch)
        if len(batch) < page:
            break
        offset += page
    return rows


def extract_zip(address):
    """Address strings look like 'CEDAR RAPIDS, IA 52404' or a multi-line
    '5218 WINDMILL CT SW\\nCEDAR RAPIDS, IA 52404' -- take the last line,
    match the trailing 5-digit zip and the city name before the state."""
    if not address:
        return None, None
    last_line = address.strip().splitlines()[-1].strip()
    m = CITY_ZIP_RE.match(last_line)
    if m:
        return m.group(3), m.group(1).strip().title()
    m2 = ZIP_RE.search(last_line)
    if m2:
        return m2.group(1), None
    return None, None


def parse_dt(value):
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    # permits.issued_date is a plain DATE column ("2026-07-14", no tz) while
    # storm_events.onset_at is timestamptz -- normalize both to UTC-aware so
    # they can be compared against `now` without raising.
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def build_neighborhoods(permits, storm_events):
    now = datetime.now(timezone.utc)
    cutoff_30 = now - timedelta(days=30)
    cutoff_90 = now - timedelta(days=90)
    cutoff_7 = now - timedelta(days=7)

    zips = {}  # zip -> {"city":..., "permits_30":[], "permits_90":[]}
    for p in permits:
        zip_code, city = extract_zip(p.get("address"))
        if not zip_code:
            continue
        issued = parse_dt(p.get("issued_date"))
        z = zips.setdefault(zip_code, {"city": city, "permits_30": [], "permits_90": []})
        if city and not z["city"]:
            z["city"] = city
        if issued is None:
            continue
        if issued >= cutoff_90:
            z["permits_90"].append(p)
        if issued >= cutoff_30:
            z["permits_30"].append(p)

    # storm_events don't carry a zip code -- match by checking whether the
    # zip's known city name appears in the storm's area_desc text (the only
    # link available between the two tables without a geocoder).
    storm_by_zip = {}
    for zip_code, z in zips.items():
        if not z["city"]:
            continue
        matches = []
        for s in storm_events:
            area = (s.get("area_desc") or "")
            if z["city"].lower() in area.lower():
                onset = parse_dt(s.get("onset_at"))
                matches.append(onset)
        matches = [m for m in matches if m is not None]
        storm_by_zip[zip_code] = matches

    neighborhoods = []
    for zip_code, z in zips.items():
        permits_30 = z["permits_30"]
        permits_90 = z["permits_90"]
        values = [p["value"] for p in permits_90 if p.get("value") is not None]
        avg_value = sum(values) / len(values) if values else 0.0

        storm_times = storm_by_zip.get(zip_code, [])
        storms_30 = [t for t in storm_times if t >= cutoff_30]
        last_storm = max(storm_times) if storm_times else None
        storm_last_7d = any(t >= cutoff_7 for t in storm_times)

        score = 0
        score += 15 * len(permits_30)
        score += 5 * len(permits_90)
        if avg_value > 20000:
            score += 20
        elif avg_value > 10000:
            score += 10
        if storms_30:
            score += 30
        if storm_last_7d:
            score += 20
        score = min(score, 99)

        if storm_last_7d:
            signal = "storm"
        elif len(permits_30) >= 3:
            signal = "permits"
        else:
            signal = "neighborhood"

        neighborhoods.append({
            "zip_code": zip_code,
            "city": z["city"],
            "state": "IA",
            "permit_count_30d": len(permits_30),
            "permit_count_90d": len(permits_90),
            "avg_job_value": round(avg_value, 2),
            "storm_events_30d": len(storms_30),
            "last_storm_at": last_storm.isoformat() if last_storm else None,
            "neighborhood_score": score,
            "signal": signal,
            "updated_at": now.isoformat(),
        })
    return neighborhoods


def push(neighborhoods):
    if not neighborhoods:
        return 0
    r = requests.post(
        f"{SUPABASE_URL}/rest/v1/neighborhoods",
        headers=WRITE_HEADERS,
        params={"on_conflict": "zip_code"},
        data=json.dumps(neighborhoods),
        timeout=30,
    )
    if r.status_code in (200, 201):
        print(f"  upserted {len(neighborhoods)} neighborhoods")
        return len(neighborhoods)
    print(f"  supabase error {r.status_code}: {r.text[:300]}")
    return 0


def run():
    print(f"[{datetime.now(timezone.utc).isoformat()}] Titan Neighborhood Scorer")
    if not table_exists("neighborhoods"):
        print("  neighborhoods table does not exist. Run this SQL in the Supabase dashboard:\n")
        print(TABLE_SQL)
        return

    permits = fetch_all("permits", select="address,value,issued_date")
    storm_events = fetch_all("storm_events", select="area_desc,onset_at")
    print(f"  {len(permits)} permits, {len(storm_events)} storm events fetched")

    neighborhoods = build_neighborhoods(permits, storm_events)
    print(f"  {len(neighborhoods)} zip codes scored")
    push(neighborhoods)
    print("Done.")


if __name__ == "__main__":
    run()
