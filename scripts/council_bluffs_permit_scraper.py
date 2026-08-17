"""
Titan Permit Scraper — Council Bluffs, IA (Pottawattamie County)
Downloads monthly permit reports from councilbluffs-ia.gov
Tries PDF then Citizenserve portal, saves to Supabase `permits` table.
"""
import os, re, datetime, requests, pdfplumber, io
from urllib.parse import urljoin

SUPABASE_URL = os.environ.get('SUPABASE_URL', 'https://yfscfuyxbluidykmpjod.supabase.co')
SUPABASE_KEY = os.environ.get('SUPABASE_SERVICE_KEY')

HEADERS = {'User-Agent': 'TitanContractingOS/1.0'}

REPORT_INDEX_URL = 'https://www.councilbluffs-ia.gov/2531/Monthly-Permit-Reports'

ROOFING_KEYWORDS = [
    'roof', 'shingle', 'storm', 'hail', 'wind', 'siding', 'gutter',
    'residential repair', 'storm damage', 'exterior', 're-roof'
]


def get_latest_report_url():
    r = requests.get(REPORT_INDEX_URL, headers=HEADERS, timeout=15)
    r.raise_for_status()
    html = r.text

    pdf_links = re.findall(r'href=["\']([^"\']*\.pdf)["\']', html, re.IGNORECASE)
    now = datetime.datetime.now()

    for delta in [0, 1]:
        target = now - datetime.timedelta(days=delta * 30)
        month_str = target.strftime('%B').lower()
        year_str = str(target.year)
        for link in pdf_links:
            if month_str in link.lower() and year_str in link:
                return urljoin('https://www.councilbluffs-ia.gov', link)

    if pdf_links:
        return urljoin('https://www.councilbluffs-ia.gov', pdf_links[0])
    return None


def parse_permits_from_pdf(pdf_bytes):
    permits = []
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for page in pdf.pages:
            text = page.extract_text() or ''
            tables = page.extract_tables()

            for table in tables:
                if not table:
                    continue
                header = [str(c).lower().strip() if c else '' for c in (table[0] or [])]
                addr_col = next((i for i, h in enumerate(header) if 'address' in h or 'location' in h or 'site' in h), None)
                type_col = next((i for i, h in enumerate(header) if 'type' in h or 'work' in h or 'description' in h or 'class' in h), None)
                permit_col = next((i for i, h in enumerate(header) if 'permit' in h or 'number' in h or 'no.' in h), None)
                val_col = next((i for i, h in enumerate(header) if 'value' in h or 'valuation' in h or 'cost' in h or 'fee' in h), None)
                date_col = next((i for i, h in enumerate(header) if 'date' in h or 'issued' in h), None)

                for row in table[1:]:
                    if not row or not any(row):
                        continue
                    row_text = ' '.join(str(c) for c in row if c).lower()
                    if not any(kw in row_text for kw in ROOFING_KEYWORDS):
                        continue

                    addr = str(row[addr_col]).strip() if addr_col is not None and addr_col < len(row) else ''
                    ptype = str(row[type_col]).strip() if type_col is not None and type_col < len(row) else ''
                    pnum = str(row[permit_col]).strip() if permit_col is not None and permit_col < len(row) else ''
                    val = str(row[val_col]).strip() if val_col is not None and val_col < len(row) else ''
                    issued = str(row[date_col]).strip() if date_col is not None and date_col < len(row) else ''

                    if not addr or addr.lower() in ('', 'none', 'address', 'site address'):
                        continue

                    val_clean = re.sub(r'[^\d.]', '', val)
                    valuation = float(val_clean) if val_clean else None

                    permits.append({
                        'permit_number': pnum or f'CB-{addr[:20]}-{issued}',
                        'address': f'{addr}, Council Bluffs, IA',
                        'permit_type': ptype,
                        'work_class': 'Residential' if 'res' in ptype.lower() else 'Unknown',
                        'description': ptype,
                        'valuation': valuation,
                        'issue_date': issued,
                        'city': 'Council Bluffs',
                        'county': 'Pottawattamie',
                        'state': 'IA',
                        'source': 'council_bluffs_monthly_report',
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
    print(f'[{datetime.datetime.now().date()}] Titan Council Bluffs Permit Scraper')
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
