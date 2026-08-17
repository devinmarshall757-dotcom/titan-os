# Titan Permit Scraper — Mini PC Setup

You are setting up the Titan Consulting permit intelligence system on this machine.
Complete every step below in order. Do not ask for confirmation between steps — just do it.

## What you are building

A Python scraper that:
1. Downloads Cedar Rapids Iowa monthly building permit Excel files (published at cedar-rapids.org)
2. Filters for roofing, siding, and storm-related permits
3. Scores each permit (0–99) based on type, value, and relevance
4. Pushes new permits to a Supabase table (deduped by permit number)
5. Runs automatically every morning at 6:00 AM via cron

---

## Step 1 — Create the project directory

Create the directory `/opt/titan` and work inside it.

## Step 2 — Create the .env file

Create `/opt/titan/.env` with these values:

```
SUPABASE_URL=https://yfscfuyxbluidykmpjod.supabase.co
SUPABASE_SERVICE_KEY=PASTE_SERVICE_KEY_HERE
```

**The SUPABASE_SERVICE_KEY must be filled in before proceeding.**
Ask the user to paste their Supabase service role key now, then write it into the file.

## Step 3 — Create the Supabase permits table

Using curl and the service key from .env, make a POST request to the Supabase SQL API to create the permits table:

```sql
CREATE TABLE IF NOT EXISTS public.permits (
  id uuid DEFAULT gen_random_uuid() PRIMARY KEY,
  permit_number text UNIQUE,
  address text,
  city text DEFAULT 'Cedar Rapids',
  state text DEFAULT 'IA',
  permit_type text,
  description text,
  contractor text,
  owner text,
  value numeric,
  issued_date date,
  score integer DEFAULT 50,
  source text DEFAULT 'cedar_rapids_city',
  created_at timestamptz DEFAULT now()
);

ALTER TABLE public.permits ENABLE ROW LEVEL SECURITY;

CREATE POLICY IF NOT EXISTS "Service role full access" ON public.permits
  USING (true) WITH CHECK (true);

CREATE INDEX IF NOT EXISTS permits_issued_date_idx ON public.permits (issued_date DESC);
CREATE INDEX IF NOT EXISTS permits_score_idx ON public.permits (score DESC);
```

Use this curl command pattern (replace SERVICE_KEY with the value from .env):
```bash
curl -X POST "https://yfscfuyxbluidykmpjod.supabase.co/rest/v1/rpc/exec_sql" \
  -H "apikey: SERVICE_KEY" \
  -H "Authorization: Bearer SERVICE_KEY" \
  -H "Content-Type: application/json" \
  -d '{"sql": "..."}'
```

If `exec_sql` RPC is not available, use the Supabase management API instead:
```bash
curl -X POST "https://api.supabase.com/v1/projects/yfscfuyxbluidykmpjod/database/query" \
  -H "Authorization: Bearer SERVICE_KEY" \
  -H "Content-Type: application/json" \
  -d '{"query": "..."}'
```

Verify the table was created by doing a GET to `/rest/v1/permits?limit=1`.

## Step 4 — Install Python dependencies

```bash
sudo apt-get install -y python3 python3-pip python3-venv
python3 -m venv /opt/titan/venv
/opt/titan/venv/bin/pip install requests openpyxl python-dotenv
```

## Step 5 — Write the scraper

Write the following Python script to `/opt/titan/permit_scraper.py`:

```python
#!/usr/bin/env python3
"""
Titan Permit Scraper — Cedar Rapids, IA
Runs daily, pushes roofing/siding permits to Supabase.
"""

import os, io, re, json, datetime, requests, openpyxl
from dotenv import load_dotenv

load_dotenv("/opt/titan/.env")

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_SERVICE_KEY"]
HEADERS = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json",
    "Prefer": "resolution=ignore-duplicates,return=minimal"
}

ROOF_KEYWORDS = [
    "roof","re-roof","reroof","shingle","siding","fascia",
    "soffit","gutter","storm","hail","wind","exterior","flashing"
]
MONTHS = ["January","February","March","April","May","June",
          "July","August","September","October","November","December"]
CR_BASE = "https://www.cedar-rapids.org/Building%20Services/Monthly%20Permit%20Reports"


def is_roofing(vals):
    text = " ".join(str(v) for v in vals if v).lower()
    return any(k in text for k in ROOF_KEYWORDS)


def score(p):
    s = 50
    text = ((p.get("permit_type") or "") + " " + (p.get("description") or "")).lower()
    if any(k in text for k in ["roof","re-roof","reroof","shingle"]): s += 25
    if any(k in text for k in ["storm","hail","wind"]): s += 20
    if any(k in text for k in ["siding","exterior"]): s += 10
    v = p.get("value") or 0
    if v > 20000: s += 15
    elif v > 10000: s += 8
    elif v > 5000: s += 3
    return min(s, 99)


def fetch_excel(year, month):
    name = MONTHS[month - 1]
    for ext in [".xls", ".xlsx"]:
        url = f"{CR_BASE}/{year}/{month}%20{name}{ext}"
        try:
            r = requests.get(url, timeout=30, allow_redirects=True,
                             headers={"User-Agent": "TitanOS/1.0"})
            if r.status_code == 200 and len(r.content) > 1000:
                print(f"  Got {name} {year}{ext}")
                return r.content
        except Exception as e:
            print(f"  fetch error: {e}")
    return None


def col(headers, names):
    for name in names:
        for i, h in enumerate(headers):
            if name in h:
                return i
    return None


def parse(content, year, month):
    wb = openpyxl.load_workbook(io.BytesIO(content), read_only=True, data_only=True)
    ws = wb.active
    rows = list(ws.iter_rows(values_only=True))
    wb.close()

    headers, header_row = [], 0
    for i, row in enumerate(rows[:10]):
        non_empty = [v for v in row if v is not None]
        if len(non_empty) >= 3:
            headers = [str(v).strip().lower() if v else "" for v in row]
            header_row = i
            break

    if not headers:
        print("  no headers found")
        return []

    print(f"  columns: {[h for h in headers if h]}")

    i_num  = col(headers, ["permit no","permit num","number","permit #"])
    i_addr = col(headers, ["address","location","site"])
    i_type = col(headers, ["type","permit type","work type"])
    i_desc = col(headers, ["description","desc","work desc","scope"])
    i_val  = col(headers, ["value","valuation","job value","estimated"])
    i_cont = col(headers, ["contractor","company","applicant"])
    i_own  = col(headers, ["owner","property owner"])
    i_date = col(headers, ["issue","issued","date","permit date"])

    def get(row, idx):
        if idx is None or idx >= len(row): return None
        v = row[idx]
        return str(v).strip() if v is not None else None

    permits = []
    for row in rows[header_row + 1:]:
        if not any(row): continue
        if not is_roofing(row): continue

        raw_val = get(row, i_val)
        value = None
        if raw_val:
            try: value = float(re.sub(r"[^\d.]", "", raw_val))
            except: pass

        raw_date = get(row, i_date)
        issued_date = datetime.date(year, month, 1).isoformat()
        if raw_date:
            if i_date is not None and isinstance(row[i_date], datetime.datetime):
                issued_date = row[i_date].date().isoformat()
            else:
                for fmt in ["%m/%d/%Y","%Y-%m-%d","%m-%d-%Y","%m/%d/%y"]:
                    try:
                        issued_date = datetime.datetime.strptime(raw_date, fmt).date().isoformat()
                        break
                    except: pass

        p = {
            "permit_number": get(row, i_num) or f"CR-{year}{month:02d}-{len(permits)}",
            "address": get(row, i_addr),
            "city": "Cedar Rapids", "state": "IA",
            "permit_type": get(row, i_type),
            "description": get(row, i_desc),
            "contractor": get(row, i_cont),
            "owner": get(row, i_own),
            "value": value,
            "issued_date": issued_date,
            "source": "cedar_rapids_city",
        }
        p["score"] = score(p)
        permits.append(p)

    return permits


def push(permits):
    if not permits: return 0
    r = requests.post(f"{SUPABASE_URL}/rest/v1/permits",
                      headers=HEADERS, data=json.dumps(permits), timeout=30)
    if r.status_code in (200, 201):
        print(f"  pushed {len(permits)} permits")
        return len(permits)
    print(f"  supabase error {r.status_code}: {r.text[:300]}")
    return 0


def run():
    today = datetime.date.today()
    print(f"[{today}] Titan Permit Scraper")

    for delta in [0, 1]:
        m = today.month - delta
        y = today.year if m > 0 else today.year - 1
        m = m if m > 0 else 12
        content = fetch_excel(y, m)
        if content:
            permits = parse(content, y, m)
            print(f"  {len(permits)} roofing/siding permits found")
            push(permits)
            break
        print(f"  no file for {MONTHS[m-1]} {y}, trying previous month")

    print("Done.")

if __name__ == "__main__":
    run()
```

## Step 6 — Run it once to verify

```bash
/opt/titan/venv/bin/python3 /opt/titan/permit_scraper.py
```

Check for output showing permits found and pushed. If 0 permits, check the column output to see if the Excel structure needs adjustment.

## Step 7 — Verify data in Supabase

```bash
curl "https://yfscfuyxbluidykmpjod.supabase.co/rest/v1/permits?order=score.desc&limit=5" \
  -H "apikey: $(grep SUPABASE_SERVICE_KEY /opt/titan/.env | cut -d= -f2)" \
  -H "Authorization: Bearer $(grep SUPABASE_SERVICE_KEY /opt/titan/.env | cut -d= -f2)"
```

You should see JSON records with addresses, scores, and permit types.

## Step 8 — Set up daily cron

Add a cron job to run every morning at 6:00 AM:

```bash
(crontab -l 2>/dev/null; echo "0 6 * * * /opt/titan/venv/bin/python3 /opt/titan/permit_scraper.py >> /var/log/titan_permits.log 2>&1") | crontab -
```

Confirm with: `crontab -l`

## Step 9 — Report back

Once complete, tell the user:
- How many permits were found and pushed
- What the top 3 highest-scored permits are (address, type, score)
- That the cron job is set for 6:00 AM daily
- Any errors encountered

The Titan admin dashboard at titanconsultingcontracting.com/admin will automatically display these permits under the Permits tab.
