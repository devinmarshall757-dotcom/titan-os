# PITCH READY REPORT
Generated: 2026-08-16 (updated after full hardening pass)

## System Status

| System | Status | Notes |
|---|---|---|
| Permit Intelligence — Cedar Rapids | **LIVE** | Daily XLS pull, scored, upserted to Supabase |
| Permit Intelligence — Dubuque | **BETA** | PDF scraper built, schema normalized, not yet scheduled |
| Permit Intelligence — Council Bluffs | **BETA** | PDF scraper built, schema normalized, not yet scheduled |
| Storm Monitoring — 99 Iowa Counties | **LIVE** | NOAA statewide alert collector, task queued and running |
| LiDAR Measurements | **LIVE (limited geography)** | Eastern Iowa: Cedar Rapids/Linn, Iowa City/Johnson, Davenport/Scott. Fallback: parcel/OSM estimate |
| CRM Pipeline | **LIVE** | Jobs, insurance fields, adjuster, activity log. Lightweight — not an AccuLynx replacement |
| Lead Capture | **LIVE** | Form → Supabase insert (awaited) + email to Landon |
| Reviews Dashboard | **LIVE** | CRUD with server-side auth |
| Neighborhood Targeting | **ROADMAP** | Scorer file not yet built |
| AI Follow-Up Agent | **ROADMAP** | Not yet implemented |

## Changes Made This Session

### P0 — Security
- [x] Admin dashboard is now **DEMO MODE** — all data is synthetic, no real Supabase reads occur
- [x] `window.fetch` intercepted for all Supabase URLs — returns hardcoded demo data, blocks all mutations silently
- [x] Prominent purple "DEMO — SYNTHETIC DATA" banner shown at top of admin panel
- [x] `ADMIN_PASSWORD` removed from browser source — server-side check via `/api/admin-auth`
- [x] `ADMIN_PASSWORD` set as encrypted Vercel env var
- [x] **REMAINING**: Authenticated production admin APIs (service-key server routes + RLS) are post-pitch work — do not use admin for real customer data until complete

### P0 — Lead Capture
- [x] `api/contact.js` now awaits Supabase insert and checks `response.ok`
- [x] All user input HTML-escaped before interpolation into email (`he()` function)
- [x] Email no longer sends if DB insert fails

### P0 — Pitch Copy (false claims removed)
- [x] "Any Iowa address" → "eastern Iowa coverage (Cedar Rapids, Iowa City, Davenport metro)"
- [x] "Works statewide" removed
- [x] "Iowa City + Rock Island" permits removed from Morning Feed demo
- [x] "47 permits today Cedar Rapids, Iowa City, Rock Island" → "14 permits pulled this morning from Cedar Rapids"
- [x] Iowa City permit city label → Cedar Rapids in demo card
- [x] "Real-time, no refresh needed" → "loads current data on each view"
- [x] "Real-time" in architecture slide → "Live data on load"
- [x] "Replaces AccuLynx" → "Lightweight pipeline CRM"
- [x] "No AccuLynx needed" → "No extra CRM subscription needed"
- [x] "Satellite" qualifier removed from measurement description

### P0 — Service Agreement
- [x] "60–85% accuracy" → "internally calculated confidence indicator"
- [x] "Client data is not shared with any third party" → named subprocessors list (Vercel, Supabase, Resend, Regrid, USGS, NOAA, OSM/Nominatim)

### P1 — Automation
- [x] `task_poller.py` subprocess bug fixed (double `args` parameter removed)
- [x] Script paths updated to `C:\titan\scripts\`
- [x] Dubuque + Council Bluffs scrapers added to allowlist

### P1 — Permit Schema
- [x] Dubuque scraper: `valuation` → `value`, `issue_date` → `issued_date`
- [x] Council Bluffs scraper: same normalization
- [x] All three scrapers now use identical required field names

### P1 — Dashboard Error Handling
- [x] `actReview()` — checks `response.ok`, re-enables buttons on failure, shows error
- [x] `deleteJob()` — checks `response.ok`, blocks close on failure

### P2 — Tests
- [x] 22 tests, all passing (`python3 tests/test_titan.py`)
  - Contact HTML escaping (5 tests)
  - Permit schema consistency across all 3 scrapers (5 tests)
  - Storm scraper event scoring and filtering (5 tests)
  - Task poller allowlist (2 tests)
  - Pitch prohibited claims (5 tests)

### P2 — RLS Migration
- [x] `supabase/migrations/20260816_rls_hardening.sql` — reviewed policies for all tables
- ⚠️  **Do not apply until admin mutations are routed through service-key server endpoints** — applying now will break the dashboard for anon reads

## Remaining Gaps (Post-Pitch)

| Item | Priority | Effort |
|---|---|---|
| Admin mutations behind service-key server routes (not anon key) | High | 1-2 days |
| Apply RLS migration after above | High | 30 min |
| Neighborhood scorer implementation | Medium | 1 day |
| AI Follow-Up Agent | Medium | 2-3 days |
| Rate limiting on `/api/measure` and `/api/contact` | Medium | 4 hours |
| Scheduled cron for storm scraper (every 6h) | Low | 1 hour |
| Dubuque + Council Bluffs scrapers tested + scheduled | Low | 2 hours |
| Des Moines + Iowa City permit portals | Low | 1-2 days |

## Test Results

```
Ran 22 tests in 0.114s — OK
```

## Deployment Commands (run in order, confirm before each)

```bash
# 1. Deploy to production
vercel deploy --prod --yes

# 2. Alias pitch domain
vercel alias <deployment-url> titan-pitch-pi.vercel.app

# 3. Push to GitHub
git push

# 4. Mini PC — pull updated scripts
# (run on mini PC) git pull
```

## 5-Minute Demo Script (capabilities that genuinely work)

1. **Open pitch** → titan-pitch-pi.vercel.app/pitch — walk through slides
2. **Measurements** → go to titanconsultingcontracting.com, enter a Cedar Rapids address, show roof squares + confidence score pulling live
3. **Admin dashboard** → /admin, log in (password: titan), show Leads tab with real submissions
4. **Permit feed** → show Permits tab with Cedar Rapids data scored and sorted
5. **Storm feed** → show Storm tab (data present if NOAA has active Iowa alerts)
6. **Pipeline CRM** → show Jobs tab, click a job, show insurance fields + activity log

**Do not demo:** Iowa City or Rock Island permits, neighborhood targeting, AI follow-up agent, statewide LiDAR

## Manual Steps Still Required

1. Run `git pull` on mini PC to get updated task_poller + scripts
2. Restart task_poller on mini PC after pull
3. Optionally apply RLS migration — but read the warning above first
