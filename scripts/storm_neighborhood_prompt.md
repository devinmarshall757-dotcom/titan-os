You are continuing to build the Titan Consulting intelligence system on this Windows machine. The permit scraper is already running at C:\titan\permit_scraper.py and pushing to Supabase. Now build three more components.

Environment facts:
- Windows machine, use C:\titan\ for all files
- Python venv is at C:\titan\venv\
- Supabase credentials are in C:\titan\.env (SUPABASE_URL and SUPABASE_SERVICE_KEY)
- Ask before installing any new packages
- Ask before creating any scheduled tasks
- Do not display or log credential values at any point

Supabase project: https://yfscfuyxbluidykmpjod.supabase.co

---

## COMPONENT 1 — storm_scraper.py

Write C:\titan\storm_scraper.py

This script hits two free NOAA endpoints (no API key needed) to get Iowa severe weather events, then pushes new ones to Supabase.

### Data sources

**Source 1 — Active NWS alerts for Iowa:**
GET https://api.weather.gov/alerts/active?area=IA
Headers: User-Agent: TitanOS/1.0 (titanconsultingcontracting.com)
Returns JSON. Path: response["features"] — array of alert objects.
Each alert has:
- properties.id — unique alert ID
- properties.event — e.g. "Severe Thunderstorm Warning", "Tornado Warning", "Flash Flood Warning"
- properties.headline
- properties.description
- properties.onset — ISO datetime
- properties.expires — ISO datetime
- properties.areaDesc — affected area description (e.g. "Linn County")
- properties.parameters.hailSize — array, e.g. ["1.75"] inches if present
- properties.parameters.windGust — array, e.g. ["60"] mph if present
- geometry — GeoJSON polygon or null

Filter for events that mention: Thunderstorm, Tornado, Hail, Wind, Hurricane, Winter Storm
Focus on Linn County (Cedar Rapids), Johnson County (Iowa City), Scott County (Bettendorf)

**Source 2 — NOAA Storm Events recent reports:**
GET https://api.weather.gov/products?type=LSR&office=KDVN
(KDVN = Quad Cities WFO, covers eastern Iowa)
Returns list of Local Storm Reports. Fetch the first result's @id URL, parse the productText for hail/wind events.

### Supabase table to create first

Before pushing data, create this table if it doesn't exist by POST to Supabase REST:

```
POST https://yfscfuyxbluidykmpjod.supabase.co/rest/v1/storm_events
```

First check if table exists:
```
GET https://yfscfuyxbluidykmpjod.supabase.co/rest/v1/storm_events?limit=1
```
If 404, the table doesn't exist. Tell the user the CREATE TABLE SQL to run in Supabase dashboard:

```sql
CREATE TABLE IF NOT EXISTS public.storm_events (
  id uuid DEFAULT gen_random_uuid() PRIMARY KEY,
  alert_id text UNIQUE,
  event_type text,
  headline text,
  description text,
  area_desc text,
  counties text[],
  hail_size_inches float,
  wind_gust_mph float,
  onset_at timestamptz,
  expires_at timestamptz,
  severity text,
  source text DEFAULT 'noaa_nws',
  created_at timestamptz DEFAULT now()
);
ALTER TABLE public.storm_events ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Service role full access" ON public.storm_events USING (true) WITH CHECK (true);
CREATE INDEX IF NOT EXISTS storm_events_onset_idx ON public.storm_events (onset_at DESC);
```

Wait for user to confirm table is created before proceeding.

### Scoring logic

score = 50
- Tornado warning: +40
- Severe thunderstorm warning: +25
- Hail >= 1.5 inches: +20
- Hail >= 1.0 inch: +10
- Wind >= 70mph: +15
- Wind >= 58mph: +8
- Linn County (Cedar Rapids): +10 bonus
score = min(score, 99)

### Push to Supabase
POST to /rest/v1/storm_events with Prefer: resolution=ignore-duplicates,return=minimal
Dedupe on alert_id

### Run schedule
Ask user before creating Task Scheduler entry. If approved: run every 6 hours (0 */6 * * * equivalent in Task Scheduler).

---

## COMPONENT 2 — neighborhood_scorer.py

Write C:\titan\neighborhood_scorer.py

This script reads existing permits and storm_events from Supabase, groups them by zip code, scores each neighborhood, and upserts into a neighborhoods table.

### Supabase table

Check if neighborhoods table exists (GET /rest/v1/neighborhoods?limit=1).
If not, give user this SQL:

```sql
CREATE TABLE IF NOT EXISTS public.neighborhoods (
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
CREATE POLICY "Service role full access" ON public.neighborhoods USING (true) WITH CHECK (true);
```

### Logic

1. Fetch all permits from /rest/v1/permits
2. Extract zip code from address field (last 5 digits of "CEDAR RAPIDS, IA 52404" → "52404")
3. Group by zip code, calculate:
   - permit_count_30d: permits with issued_date >= 30 days ago
   - permit_count_90d: permits with issued_date >= 90 days ago
   - avg_job_value: average value of permits in last 90 days
4. Fetch all storm_events from /rest/v1/storm_events
5. Match storm events to zip codes by checking if the zip's city appears in area_desc
6. Calculate storm_events_30d and last_storm_at per zip

### Neighborhood score formula

score = 0
- Each permit in last 30d: +15
- Each permit in last 90d: +5
- avg_job_value > 20000: +20
- avg_job_value > 10000: +10
- storm in last 30d: +30
- storm in last 7d: +20 bonus
score = min(score, 99)

### Signal field
- If storm in last 7d: signal = "storm"
- Elif permit_count_30d >= 3: signal = "permits"
- Else: signal = "neighborhood"

### Upsert
POST to /rest/v1/neighborhoods with Prefer: resolution=merge-duplicates,return=minimal on zip_code

Run schedule: after permit scraper (6:15 AM daily). Ask before scheduling.

---

## COMPONENT 3 — Report back

After both scripts are written and tested:

1. Run storm_scraper.py — report how many active Iowa storm alerts were found and pushed
2. Run neighborhood_scorer.py — report the top 5 neighborhoods by score with their signal type
3. Show the final file list in C:\titan\
4. List what still needs Task Scheduler setup and ask for approval

Do not proceed to Task Scheduler without explicit user approval for each job.
