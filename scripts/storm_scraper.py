"""
Titan Storm Scraper — ALL 99 Iowa Counties + statewide Illinois/Wisconsin border zones
Polls NOAA Weather.gov every 6 hours for severe weather events.
Saves to Supabase `storm_events` table.
"""
import os, json, datetime, requests

SUPABASE_URL = os.environ.get('SUPABASE_URL', 'https://yfscfuyxbluidykmpjod.supabase.co')
SUPABASE_KEY = os.environ.get('SUPABASE_SERVICE_KEY')

HEADERS = {'User-Agent': 'TitanContractingOS/1.0 (contact: Landon.diehl@titanconsultingcontracting.com)'}

# Roofing-relevant event types
ROOFING_EVENTS = {
    'Severe Thunderstorm Warning',
    'Severe Thunderstorm Watch',
    'Tornado Warning',
    'Tornado Watch',
    'High Wind Warning',
    'High Wind Watch',
    'Wind Advisory',
    'Special Weather Statement',
    'Flash Flood Warning',
}

# States to monitor — IA = all 99 counties, IL for Rock Island border area
STATES = ['IA', 'IL']


def fetch_alerts(state):
    url = f'https://api.weather.gov/alerts/active?area={state}'
    r = requests.get(url, headers=HEADERS, timeout=15)
    r.raise_for_status()
    return r.json().get('features', [])


def extract_hail_size(alert):
    params = alert.get('properties', {}).get('parameters', {})
    hail = params.get('maxHailSize', params.get('hailSize', [None]))[0]
    try:
        return float(hail) if hail else None
    except (ValueError, TypeError):
        return None


def process_alert(feature):
    props = feature.get('properties', {})
    event = props.get('event', '')
    if event not in ROOFING_EVENTS:
        return None

    onset = props.get('onset') or props.get('effective') or datetime.datetime.utcnow().isoformat()
    ends = props.get('ends') or props.get('expires')
    area_desc = props.get('areaDesc', '')
    headline = props.get('headline', '')
    description = props.get('description', '')
    severity = props.get('severity', 'Unknown')
    certainty = props.get('certainty', 'Unknown')
    hail_size = extract_hail_size(feature)

    # Score: Tornado=10, Severe Tstorm Warning w/ hail>=1"=9, High Wind Warning=8, etc.
    score = 5
    if 'Tornado Warning' in event: score = 10
    elif 'Tornado Watch' in event: score = 8
    elif 'Severe Thunderstorm Warning' in event:
        score = 9 if hail_size and hail_size >= 1.0 else 7
    elif 'High Wind Warning' in event: score = 8
    elif 'Severe Thunderstorm Watch' in event: score = 6

    # Extract affected counties from areaDesc
    counties = [c.strip() for c in area_desc.replace(' and ', ', ').split(',') if c.strip()]

    return {
        'event_type': event,
        'severity': severity,
        'certainty': certainty,
        'area_desc': area_desc,
        'headline': headline,
        'description': description[:2000],
        'hail_size_inches': hail_size,
        'score': score,
        'onset_at': onset,
        'expires_at': ends,
        'counties': counties,
        'source': 'noaa_nws',
        'noaa_id': props.get('@id', feature.get('id', '')),
        'created_at': datetime.datetime.utcnow().isoformat(),
    }


def upsert_events(events):
    if not events:
        return
    url = f'{SUPABASE_URL}/rest/v1/storm_events'
    headers = {
        'apikey': SUPABASE_KEY,
        'Authorization': f'Bearer {SUPABASE_KEY}',
        'Content-Type': 'application/json',
        'Prefer': 'resolution=merge-duplicates',
    }
    r = requests.post(url, headers=headers, json=events, timeout=15)
    if r.status_code not in (200, 201):
        print(f'  supabase error {r.status_code}: {r.text[:200]}')
    else:
        print(f'  upserted {len(events)} storm events')


def main():
    now = datetime.datetime.utcnow().strftime('%Y-%m-%dT%H:%M')
    print(f'[{now}] Titan Storm Scraper — Iowa statewide + IL border')

    all_events = []
    for state in STATES:
        try:
            features = fetch_alerts(state)
            print(f'  {state}: {len(features)} active alerts')
            for f in features:
                evt = process_alert(f)
                if evt:
                    all_events.append(evt)
        except Exception as e:
            print(f'  {state} error: {e}')

    # Deduplicate by noaa_id
    seen = set()
    unique = []
    for e in all_events:
        if e['noaa_id'] not in seen:
            seen.add(e['noaa_id'])
            unique.append(e)

    roofing_count = len(unique)
    print(f'  {roofing_count} roofing-relevant alerts total')
    upsert_events(unique)
    print('Done.')


if __name__ == '__main__':
    main()
