# PITCH READY REPORT
Generated: 2026-08-16 (updated after final pitch-readiness pass)

## GO / NO-GO Decisions

| Context | Decision | Condition |
|---|---|---|
| Pitch presentation | **GO** | All false claims removed; demo build clearly labeled |
| Controlled Cedar Rapids measurement demo | **GO** | Geocode → /api/measure → display result; eastern Iowa LiDAR only |
| Synthetic admin demo | **GO** | DEMO_MODE active; purple banner; no real data shown |
| Production customer use | **NO-GO** | Authenticated server APIs and RLS not yet deployed |
| Agreement signing | **CONDITIONAL GO** | Section 7a acceptance requirements must be agreed to in writing before client data enters the system |

---

## System Status

| System | Status | Notes |
|---|---|---|
| Permit Intelligence — Cedar Rapids | **LIVE** | Daily XLS pull, scored, upserted to Supabase |
| Permit Intelligence — Dubuque | **BETA** | PDF scraper built, schema normalized, not yet scheduled |
| Permit Intelligence — Council Bluffs | **BETA** | PDF scraper built, schema normalized, not yet scheduled |
| Storm Monitoring — 99 Iowa Counties | **IMPLEMENTED** | NOAA statewide alert collector built and tested. Scheduled runs depend on mini PC staying online |
| LiDAR Measurements | **LIVE (limited geography)** | Eastern Iowa: Cedar Rapids/Linn, Iowa City/Johnson, Davenport/Scott. Experimental — field verification required. Fallback: parcel/OSM estimate |
| CRM Pipeline | **SYNTHETIC DEMO** | Admin dashboard uses `window.fetch` interceptor with hardcoded demo data. No real job, insurance, or adjuster data is stored or displayed. Production activation requires authenticated server APIs + RLS |
| Lead Capture | **LIVE** | Form → Supabase insert (awaited, checked) + email to Landon |
| Reviews Dashboard | **SYNTHETIC DEMO** | Same DEMO_MODE intercept as CRM. No real review data. Production activation requires authenticated server APIs + RLS |
| Neighborhood Targeting | **ROADMAP** | Scorer file not yet built |
| AI Follow-Up Agent | **ROADMAP** | Not yet implemented |

---

## Admin Interface — Demo Status

The admin dashboard at /admin is a **synthetic demonstration build**. Key facts:

- `DEMO_MODE = true` is set in `admin/reviews.html`
- A `window.fetch` interceptor blocks all Supabase reads and writes
- All data shown (storms, permits, leads, measurements, reviews, jobs) is hardcoded synthetic data
- A purple banner reads: "DEMO — SYNTHETIC DATA · No real leads, reviews, or customer information is displayed"
- Admin password is checked server-side via `/api/admin-auth.js` (HMAC token). Server-side password checking alone is **not production authentication**

**Real customer data must not enter the system until:**
1. Authenticated server-side admin APIs are deployed (service-role key, server routes only)
2. RLS migration is applied
3. Anonymous access to private tables is verified as denied
4. Read/write smoke tests pass against production DB

---

## Changes Made This Pass

### Pitch Copy — False Claims Removed
- [x] "running together in real time" → "available together in one unified dashboard"
- [x] "Real-Time Dashboard" heading → "Unified Dashboard"
- [x] "Watch it update in real time" removed
- [x] "Here's exactly what's running right now" → "what's implemented"
- [x] Storm monitoring "Live Now" pill → "Implemented" (roadmap slide + architecture slide)
- [x] Job Pipeline CRM "Live Now" pill → "Demo Build" (purple)
- [x] LiDAR "Live Now" pill → "Live · Eastern Iowa" (blue)
- [x] Close slide paragraph rewritten with per-system accuracy
- [x] "What's live today" checklist replaced with accurate per-item status (green/blue/purple dots)
- [x] "Built · tested · running" → "Demo build · locally tested"

### Service Agreement — Accuracy
- [x] CRM Pipeline: "Live" → "Demo — production activation pending authenticated admin APIs and RLS deployment"
- [x] Reviews Dashboard: "Live" → "Demo — production activation pending authenticated admin APIs and RLS deployment"
- [x] New Section 7a: Admin Interface — Demo Status with 4 acceptance requirements
- [x] Explicit statement: "Server-side password checking alone does not constitute production authentication"

### Measurement Boundary Hardening
- [x] `api/ept_fetch.py`: `LidarCoverageError` exception class added (safe public error, no internal details)
- [x] `api/ept_fetch.py`: Empty node list raises `LidarCoverageError` before `np.concatenate`
- [x] `api/ept_fetch.py`: Empty downloaded point arrays handled — skipped per node, raises if all empty
- [x] `api/measure_lidar.py`: Content-Length required; capped at 32 KB
- [x] `api/measure_lidar.py`: Rejects malformed JSON (explicit try/except)
- [x] `api/measure_lidar.py`: Validates lat/lon are finite numbers
- [x] `api/measure_lidar.py`: Validates latitude -90 to 90, longitude -180 to 180
- [x] `api/measure_lidar.py`: Validates parcel_geojson is null or Polygon/MultiPolygon
- [x] `api/measure_lidar.py`: Rejects parcel rings > 500 coordinates
- [x] `api/measure_lidar.py`: Internal errors return generic "Measurement unavailable"; diagnostics logged server-side only
- [x] `api/measure.js`: Rejects non-string address; trims and normalizes whitespace; rejects > 500 chars
- [x] `api/measure.js`: `measurement_method` and `manual_verification_required: true` preserved on all 3 result paths
- [x] `api/measure.js`: Fallback comment explicitly states "NOT LiDAR"

### Tests — 52/52 Passing
- [x] `TestEptFetch`: empty node list → `LidarCoverageError`
- [x] `TestEptFetch`: empty point arrays → `LidarCoverageError`
- [x] `TestMeasureLidarValidation`: invalid parcel type rejected
- [x] `TestMeasureLidarValidation`: null parcel accepted
- [x] `TestMeasureLidarValidation`: valid Polygon accepted
- [x] `TestMeasureLidarValidation`: oversized ring rejected
- [x] `TestMeasureJsStatic`: address type check, length limit, trim present in source
- [x] `TestMeasureJsStatic`: all 4 `measurement_method` values present
- [x] `TestMeasureJsStatic`: `manual_verification_required` on ≥ 3 paths
- [x] `TestMeasureJsStatic`: fallback path labeled NOT LiDAR
- [x] `TestPitchClaims`: "running together in real time" absent
- [x] `TestPitchClaims`: CRM not labeled Live Now (p-green pill)
- [x] `TestPitchClaims`: "Built · tested · running" absent
- [x] `TestServiceAgreement`: CRM and Reviews marked Demo
- [x] `TestServiceAgreement`: RLS, anonymous access, smoke tests mentioned
- [x] `TestServiceAgreement`: server-side password alone rejected

---

## Test Results

```
python3 -m unittest discover -s tests -v
Ran 52 tests in 0.186s — OK
```

```
python3 -m compileall -q api scripts → OK
node --check api/contact.js api/measure.js api/admin-auth.js → OK
```

---

## Remaining Gaps (Post-Pitch, in Priority Order)

| Item | Priority | Effort |
|---|---|---|
| Authenticated server-side admin APIs (service-role, not anon key) | **P0 before real data** | 1–2 days |
| Apply RLS migration after above | **P0 before real data** | 30 min |
| Verify anonymous access denied (smoke tests) | **P0 before real data** | 1 hour |
| Rate limiting on `/api/measure` and `/api/contact` | Medium | 4 hours |
| Neighborhood scorer implementation | Medium | 1 day |
| AI Follow-Up Agent | Medium | 2–3 days |
| Scheduled cron for storm scraper (every 6h) | Low | 1 hour |
| Dubuque + Council Bluffs scrapers tested + scheduled | Low | 2 hours |
| Des Moines + Iowa City permit portals | Low | 1–2 days |

---

## 5-Minute Demo Script

1. **Open pitch** → titan-pitch-pi.vercel.app/pitch — walk through slides
2. **Measurements** → titanconsultingcontracting.com, enter a Cedar Rapids address, show roof squares + quality indicator pulling live
3. **Admin dashboard** → /admin, log in, show DEMO banner, walk Leads / Permits / Storm tabs
4. **Pipeline CRM** → Jobs tab, click a job, show insurance fields + activity log (synthetic data)
5. **Permit feed** → Permits tab with Cedar Rapids data scored and sorted

**Do not demo as production:** CRM writes, reviews mutations, Iowa City/Rock Island permits, neighborhood targeting, AI agent, statewide LiDAR

---

## Manual Steps Before Pitch

1. Run `cd C:\titan; git pull` on mini PC (gets fixed task_poller + hardened scrapers)
2. Restart task_poller on mini PC after pull
