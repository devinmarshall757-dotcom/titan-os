"""
Titan Permit Scraper — Dubuque, IA (Dubuque County)
Downloads monthly PDF permit reports from cityofdubuque.org
Parses with pdfplumber, saves to Supabase `permits` table.
"""
import os, re, datetime, requests, pdfplumber, io

SUPABASE_URL = os.environ.get('SUPABASE_URL', 'https://yfscfuyxbluidykmpjod.supabase.co')
SUPABASE_KEY = os.environ.get('SUPABASE_SERVICE_KEY')

HEADERS = {'User-Agent': 'TitanContractingOS/1.0'}

# Dubuque monthly permit report index page
REPORT_INDEX_URL = 'https://www.cityofdubuque.org/2364/Monthly-Permit-Reports'

ROOFING_KEYWORDS = [
    'roof', 'shingle', 'storm', 'hail', 'wind', 'siding', 'gutter',
    'residential repair', 'storm damage', 'exterior'
]


def get_latest_report_url():
    """Scrape index page to find this month's (or last month's) PDF URL."""
    r = requests.get(REPORT_INDEX_URL, headers=HEADERS, timeout=15)
    r.raise_for_status()
    html = r.text

    # Find PDF links — pattern: href="...MonthYear....pdf" or similar
    pdf_links = re.findall(r'href=["\']([^"\']*\.pdf)["\']', html, re.IGNORECASE)

    now = datetime.datetime.now()
    # Try current month then last month
    for delta in [0, 1]:
        target = now - datetime.timedelta(days=delta * 30)
        month_str = target.strftime('%B').lower()
        year_str = str(target.year)
        for link in pdf_links:
            if month_str in link.lower() and year_str in link:
                return link if link.startswith('http') else f'https://www.cityofdubuque.org{link}'

    # Fall back to first PDF found
    if pdf_links:
        link = pdf_links[0]
        return link if link.startswith('http') else f'https://www.cityofdubuque.org{link}'
    return None


def parse_permits_from_pdf(pdf_bytes):
    """Extract roofing-related permits from the monthly PDF."""
    permits = []
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for page in pdf.pages:
            tables = page.extract_tables()
            for table in tables:
                if not table:
                    continue
                # Find header row
                header = [str(c).lower().strip() if c else '' for c in (table[0] or [])]
                addr_col = next((i for i, h in enumerate(header) if 'address' in h or 'location' in h), None)
                type_col = next((i for i, h in enumerate(header) if 'type' in h or 'work' in h or 'description' in h), None)
                permit_col = next((i for i, h in enumerate(header) if 'permit' in h and 'number' in h or 'no' in h), None)
                val_col = next((i for i, h in enumerate(header) if 'value' in h or 'valuation' in h or 'cost' in h), None)
                date_col = next((i for i, h in enumerate(header) if 'date' in h or 'issued' in h), None)

                for row in table[1:]:
                    if not row or not any(row):
                        continue
                    row_text = ' '.join(str(c) for c in row if c).lower()

                    # Filter for roofing-related permits
                    if not any(kw in row_text for kw in ROOFING_KEYWORDS):
                        continue

                    addr = str(row[addr_col]).strip() if addr_col is not None and addr_col < len(row) else ''
                    ptype = str(row[type_col]).strip() if type_col is not None and type_col < len(row) else ''
                    pnum = str(row[permit_col]).strip() if permit_col is not None and permit_col < len(row) else ''
                    val = str(row[val_col]).strip() if val_col is not None and val_col < len(row) else ''
                    issued = str(row[date_col]).strip() if date_col is not None and date_col < len(row) else ''

                    if not addr or addr.lower() in ('', 'none', 'address'):
                        continue

                    # Clean valuation
                    val_clean = re.sub(r'[^\d.]', '', val)
                    valuation = float(val_clean) if val_clean else None

                    permits.append({
                        'permit_number': pnum or f'DUB-{addr[:20]}-{issued}',
                        'address': f'{addr}, Dubuque, IA',
                        'permit_type': ptype,
                        'work_class': 'Residential' if 'res' in ptype.lower() else 'Unknown',
                        'description': ptype,
                        'valuation': valuation,
                        'issue_date': issued,
                        'city': 'Dubuque',
                        'county': 'Dubuque',
                        'state': 'IA',
                        'source': 'dubuque_monthly_report',
                    })
    return permits


def upsert_permits(permits):
    if not permits:
        return
    url = f'{SUPABASE_URL}/rest/v1/permits'
    headers = {
        'apikey': SUPABASE_KEY,
        'Authorization': f'Bearer {SUPABASE_KEY}',
        'Content-Type': 'application/json',
        'Prefer': 'resolution=ignore-duplicates',
    }
    r = requests.post(url, headers=headers, json=permits, timeout=15)
    if r.status_code not in (200, 201):
        print(f'  supabase error {r.status_code}: {r.text[:200]}')
    else:
        print(f'  saved {len(permits)} permits')


def main():
    print(f'[{datetime.datetime.now().date()}] Titan Dubuque Permit Scraper')
    try:
        pdf_url = get_latest_report_url()
        if not pdf_url:
            print('  no PDF report found')
            return
        print(f'  downloading: {pdf_url}')
        r = requests.get(pdf_url, headers=HEADERS, timeout=30)
        r.raise_for_status()
        permits = parse_permits_from_pdf(r.content)
        print(f'  {len(permits)} roofing permits found')
        upsert_permits(permits)
    except Exception as e:
        print(f'  error: {e}')
    print('Done.')


if __name__ == '__main__':
    main()
