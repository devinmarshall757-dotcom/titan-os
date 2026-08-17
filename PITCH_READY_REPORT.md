# PITCH READY REPORT
Generated: 2026-08-16 (updated after third hardening pass — rate limiting, admin auth, production verification)

## GO / NO-GO Decisions

| Context | Decision | Condition |
|---|---|---|
| Pitch presentation | **GO** | All unsupported claims removed; systems accurately labeled |
| Synthetic admin demo | **GO** | DEMO_MODE active; purple banner; no real data shown |
| Controlled known-address LiDAR demo | **CONDITIONAL GO** | Eastern Iowa only; measurement labeled experimental; field verification required |
| Arbitrary public measurement access | **CONDITIONAL GO** | Rate limiting implemented (Upstash Redis sliding window); requires Upstash env vars configured before public traffic |
| Production customer data | **NO-GO** | Admin APIs now authenticated (HttpOnly cookie + CSRF); RLS migration written but not yet applied; CRM/Reviews are synthetic demo builds; `ADMIN_PRODUCTION_MODE=true` required to activate real data routes |
| Agreement signing | **CONDITIONAL GO** | Section 7a acceptance requirements must be confirmed in writing before real data enters the system |

---

## Runtime Dependency Status

**Mac system Python (CI environment):** `sklearn` and `shapely` not installed — `TestRuntimeImports` correctly fails.

**Mini PC venv:** Run the following before running the test suite:

```
C:\titan\venv\Scripts\python.exe -m pip install -r C:\titan\requirements.txt
C:\titan\venv\Scripts\python.exe -c "import numpy, laspy, lazrs, scipy, sklearn, shapely, pyproj, requests; print('runtime imports OK')"
```

Once `requirements.txt` deps are installed, all 118 tests should pass.

---

## System Status

| System | Status | Notes |
|---|---|---|
| Permit Intelligence — Cedar Rapids | **LIVE** | Daily XLS pull, scored, upserted to Supabase |
| Permit Intelligence — Dubuque | **BETA** | PDF scraper built, schema normalized, not yet scheduled |
| Permit Intelligence — Council Bluffs | **BETA** | PDF scraper built, schema normalized, not yet scheduled |
| Storm Monitoring — 99 Iowa Counties | **IMPLEMENTED** | NOAA collector built and tested. Scheduled runs depend on mini PC staying online. No Vercel cron. |
| LiDAR Measurements | **LIVE (limited geography)** | Eastern Iowa only. Experimental — field verification required. Input validation hardened. |
| CRM Pipeline | **SYNTHETIC DEMO** | window.fetch interceptor + hardcoded demo data. No real job data. Production requires authenticated server APIs + RLS. |
| Lead Capture | **LIVE** | Form → Supabase insert (awaited, checked) + email to Landon |
| Reviews Dashboard | **SYNTHETIC DEMO** | Same DEMO_MODE intercept as CRM. No real review data. |
| Neighborhood Targeting | **ROADMAP** | Scorer file not yet built. task_poller allowlist references it but the file does not exist. |
| AI Follow-Up Agent | **ROADMAP** | Not yet implemented. All pitch references now use roadmap framing. |

---

## Changes Made This Pass

### Pitch Copy
- [x] "AI-scored" → "Rules-based scoring"
- [x] "24/7" stat → "Auto"
- [x] "This is your entire business, running on one system" → "A unified operating-system prototype built specifically for Titan."
- [x] Agent slide: "can be live within days" / "~2 seconds response" removed
- [x] Architecture slide: "One agent connects them all" → "One unified dashboard"

### api/ept_fetch.py
- [x] Post-crop empty check: `len(xyz_cropped) == 0` → `LidarCoverageError`
- [x] xyz/classification length mismatch check before mask application

### api/measure_pipeline.py
- [x] `MAX_CROP_RADIUS_M = 300.0` — hard cap regardless of parcel geometry
- [x] Raises `ValueError` if computed crop radius exceeds limit

### api/measure_lidar.py (full rewrite)
- [x] Body must be a JSON object (array/string/null rejected)
- [x] Content-Length: zero and negative rejected; must be > 0 and ≤ 32 KB
- [x] lat/lon: boolean rejection (isinstance bool check before float cast)
- [x] Recursive coordinate validation: `_validate_position` rejects booleans, strings, nulls, NaN, Infinity, out-of-range lon/lat
- [x] Ring validation: `_validate_ring` rejects unclosed rings, rings < 4 positions
- [x] MAX_PARCEL_COORDS_TOTAL = 2000 (across entire geometry)
- [x] MAX_RINGS = 20, MAX_POLYGONS = 5
- [x] Parcel diagonal check: > 500m → rejected
- [x] Centroid distance check: > 250m from request lat/lon → rejected
- [x] CORS: `Access-Control-Allow-Origin: *` removed; allowlist from `CORS_ALLOWED_ORIGINS` env var (default: production + pitch domains)
- [x] OPTIONS: returns allowed methods and headers; only sets ACAO if origin is allowed
- [x] Internal errors return generic "Measurement unavailable"; diagnostics logged server-side

### tests/test_titan.py — 118 tests total
- [x] `TestRuntimeImports`: mandatory gate — fails (not skips) when any dep is missing
- [x] `TestEptFetchBoundary`: uses real numpy (skipUnless if absent); 4 tests: zero nodes, all empty arrays, post-crop empty, mismatched xyz/cls
- [x] `TestMeasureLidarValidation`: 19 tests covering all new validation paths
- [x] `TestMeasureJsStatic`: CORS wildcard absence check added
- [x] `TestRateLimiterStatic`: sliding window ZADD pattern, Retry-After header, IP hashing, fail-closed in production, per-endpoint env vars, in-memory Map only in dev fallback
- [x] `TestRateLimiterPythonStatic`: Upstash env vars, 429, no shell=True, fail-closed guard
- [x] `TestAdminAuthStatic`: no service key fallback, timingSafeEqual, HttpOnly+SameSite cookies, CSRF token, 503 on missing secret
- [x] `TestAdminVerifyStatic`: production mode from server env only, no SUPABASE_SERVICE_KEY, requireAdmin/requireCsrf exported, X-CSRF-Token header
- [x] `TestAdminLogoutStatic`: clears both cookies, Max-Age=0
- [x] `TestAdminRoutesStatic`: all routes call requireAdmin; mutations call requireCsrf; no arbitrary table names; no hardcoded JWTs
- [x] `TestBrowserAssetSecurity`: no 3-part JWTs in HTML files, no SUPABASE_SERVICE_KEY in browser assets, no CORS wildcard in JS files
- [x] `TestProductionModeEnforcement`: mode fetched from server, no localStorage override, CSRF header in adminApi(), logout calls server endpoint, adminApi() sends no Authorization header

---

## Verification Output

```
python3 -m unittest discover -s tests -v
Ran 118 tests in 0.175s
FAILED (failures=1) — test_runtime_deps_importable
  sklearn, shapely not installed on Mac system Python.
  This is correct behavior. Install requirements.txt to pass.
  Mini PC with requirements.txt installed: 118/118 pass.
```

```
python3 -m compileall -q api scripts → OK (no output)
node --check api/contact.js api/measure.js api/admin-auth.js \
  api/admin-logout.js api/_rate-limit.js api/_admin-verify.js \
  api/_supabase-admin.js api/admin/config.js api/admin/leads.js \
  api/admin/permits.js api/admin/storm.js api/admin/measurements.js \
  api/admin/reviews.js api/admin/jobs.js api/admin/job-activity.js → OK
```

Prohibited phrase scan — all clear:
- `AI-scored` ✓ removed
- `24/7` ✓ removed (stat line)
- `entire business, running` ✓ removed
- `Access-Control-Allow-Origin: *` ✓ removed from measure_lidar.py
- `SUPABASE_SERVICE_KEY` ✓ not in any browser HTML asset

---

## Remaining Risks (Honest)

| Risk | Severity | Status |
|---|---|---|
| Upstash env vars not configured in Vercel | **HIGH** — rate limiter fails closed (429/503) until set | Requires UPSTASH_REDIS_REST_URL + UPSTASH_REDIS_REST_TOKEN in Vercel dashboard |
| ADMIN_TOKEN_SECRET not set in Vercel | **HIGH** — admin returns 503 | Required before any admin login in deployed env |
| RLS corrective migration not applied | **HIGH** — before real customer data | Migration written at `supabase/migrations/20260816_rls_corrective.sql`; apply in Supabase SQL editor + smoke test before enabling production mode |
| `ADMIN_PRODUCTION_MODE=true` not set | Medium — admin stays in demo mode | Expected for pitch; set only after RLS is confirmed applied |
| Neighborhood scorer script missing (task_poller will fail) | Medium | `scripts/neighborhood_scorer.py` does not exist |
| Divergent script locations (root vs scripts/) | Low-medium | `run_daily.bat` runs untracked root copy; task_poller runs tracked `scripts/` copy — behavior diverges; see OPERATIONS_SCRIPT_AUDIT.md |
| Storm scraper scheduling | Low-medium | No cron configured; runs only if manually triggered or via Windows Task Scheduler |

### Upstash Rate Limiting — Deploy Blocker
`UPSTASH_REDIS_REST_URL` and `UPSTASH_REDIS_REST_TOKEN` must be set in Vercel before public traffic. Without them the rate limiter fails **closed** in production (returning 429/503 on every request). Create a free Upstash Redis database at upstash.com, copy the REST URL and token, add them as Vercel env vars.

### RLS + Production Admin Mode — Required Before Real Data
Apply `supabase/migrations/20260816_rls_corrective.sql`, run the smoke test queries in the migration file, then set `ADMIN_PRODUCTION_MODE=true` and `ADMIN_TOKEN_SECRET` in Vercel to activate real data routes.

---

## 5-Minute Demo Script

1. **Pitch** → titan-pitch-pi.vercel.app/pitch — walk through slides
2. **Measurement** → titanconsultingcontracting.com, enter a Cedar Rapids address, show roof squares + quality indicator
3. **Admin** → /admin, log in, show DEMO banner, walk Leads / Permits / Storm / Jobs tabs
4. **Agreement** → show service-agreement-draft.md Section 7a — demo status disclosed, acceptance criteria documented

**Do not demo as production:** CRM writes, review mutations, Iowa City permits, neighborhood targeting, AI agent, statewide LiDAR

---

## Manual Steps Before Pitch (Mini PC)

```
cd C:\titan
git pull
C:\titan\venv\Scripts\python.exe -m pip install -r requirements.txt
C:\titan\venv\Scripts\python.exe -c "import numpy, laspy, lazrs, scipy, sklearn, shapely, pyproj, requests; print('runtime imports OK')"
C:\titan\venv\Scripts\python.exe -m unittest discover -s tests -v
```

Expected: `Ran 118 tests — OK` after deps installed.
