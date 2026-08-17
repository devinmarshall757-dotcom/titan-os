# TITAN OPERATING SYSTEM
## Software Services Agreement — Draft

**Service Provider:** Devin Marshall / [Business Entity]
**Client:** Landon Diehl — Titan Consulting Contracting
**Effective Date:** _______________
**Agreement Version:** 1.0

---

## 1. SERVICES

Service Provider agrees to build, host, and maintain the Titan Operating System ("Titan OS") — a custom software platform for Client's roofing contracting business. Titan OS includes the following modules:

### 1.1 Systems Included (Live at Signing)

| System | Description | Status |
|---|---|---|
| **Permit Intelligence** | Daily pull of residential roofing permits filed in Cedar Rapids, IA. Filtered and scored for outreach priority. | Live |
| **Storm Monitoring** | 24/7 NOAA weather alert monitoring across all 99 Iowa counties. Hail, tornado, and wind events scored and surfaced as leads. | Live |
| **LiDAR Measurements** | Experimental roof measurement estimates using USGS 3DEP LiDAR data where available, with parcel/OSM-derived fallbacks. Returns square footage, roofing squares, pitch, and an internal quality indicator (not validated accuracy). Currently covers eastern Iowa (Cedar Rapids/Linn, Iowa City/Johnson, Davenport/Scott). All results require field verification before use in quotes, contracts, or material orders. | Live (limited geography) |
| **CRM Pipeline** | Job management dashboard. Tracks leads through pipeline stages, captures insurance carrier, claim number, adjuster name, and job activity log. | Demo — production activation pending authenticated admin APIs and RLS deployment |
| **Lead Capture** | Web form at Client's domain that saves submissions to CRM automatically. | Live |
| **Reviews Dashboard** | Internal dashboard for managing and tracking client reviews. | Demo — production activation pending authenticated admin APIs and RLS deployment |

### 1.2 Roadmap Items (Included in Retainer, Delivered Within 3–5 Business Days of Payment)

| Feature | Description |
|---|---|
| **Neighborhood Targeting Cross-County** | Permit intelligence expanded to Client's target counties beyond Cedar Rapids. Same daily scored feed, cross-county. |
| **AI Follow-Up Agent** | When a lead enters the system, the agent drafts an outreach text. Client reviews and approves before it sends. No manual drafting required. |

> **Note:** Roadmap items are included in the base retainer. No additional charges. Timeline begins from date of first payment received.

---

## 2. HOSTING & INFRASTRUCTURE

- Titan OS is hosted on Vercel (cloud) and accessible at Client's domain (titanconsultingcontracting.com)
- Backend data runs on a dedicated Supabase (PostgreSQL) database
- Data scrapers run on a dedicated server maintained by Service Provider
- Client data is processed through the following subprocessors as required to deliver the service: Vercel (hosting), Supabase (database), Resend (email delivery), Regrid (parcel data), USGS (LiDAR elevation data), NOAA (weather alerts), OpenStreetMap/Nominatim (geocoding). Client data is not sold or used outside of service delivery.
- No OpenAI or shared AI infrastructure — dedicated server for Client's business

---

## 3. PRICING

| Item | Amount |
|---|---|
| Monthly Retainer | $1,000 / month |
| Setup / Onboarding Fee | $_______ (one-time) |
| **Total Month 1** | **$_______** |

- Retainer covers: hosting, maintenance, all system updates, roadmap delivery, and support
- Billing cycle: monthly, due on the _____ of each month
- Payment method: _______________
- Late payment grace period: 5 business days

---

## 4. WHAT CLIENT PROVIDES

- Domain access (for deployment aliasing) — or Service Provider can handle
- Confirmation of target counties for permit expansion
- Approval on outreach texts drafted by AI Follow-Up Agent before sending
- Feedback on system behavior within 48 hours of reported issues

---

## 5. SUPPORT & MAINTENANCE

- Service Provider will maintain all systems and address bugs or downtime
- Response time for critical issues (system down): within 24 hours
- Non-critical requests: within 3 business days
- System updates and improvements are included in the retainer — no surprise invoices

---

## 6. DATA & OWNERSHIP

- All data collected by Titan OS (leads, permits, storm events, job records) belongs to Client
- Upon termination, Client receives a full export of their data within 5 business days
- Service Provider retains ownership of the Titan OS codebase and underlying software

---

## 7. TERM & TERMINATION

- Initial term: month-to-month (no lock-in)
- Either party may terminate with 30 days written notice
- Client is not responsible for payment beyond the current billing period after notice is given
- Service Provider will keep systems live through the end of the paid period

---

## 7a. ADMIN INTERFACE — DEMO STATUS

The current CRM Pipeline and Reviews Dashboard are implemented as a synthetic demonstration build. The admin interface at /admin displays only pre-populated synthetic data and must not be used to hold, display, or process real customer, insurance, claim, adjuster, or review information until the following acceptance requirements are met:

1. Authenticated server-side admin APIs are deployed using the Supabase service-role key (server routes only — browser-side access to service-role keys is not permitted and does not satisfy this requirement).
2. Row-Level Security (RLS) is applied to all relevant tables via the prepared migration.
3. Anonymous access to private tables (leads, jobs, job_activity, reviews, measurements) is verified as denied by test.
4. Read and write smoke tests pass against the production database with the new authenticated routes.

Server-side password checking alone does not constitute production authentication. CRM and Reviews are considered "Live" only after all four requirements above are verified and documented.

---

## 8. LIMITATIONS

- Measurement confidence indicator: USGS LiDAR data returns an internally calculated confidence indicator (not a validated accuracy percentage). Measurements are estimates based on available aerial and parcel data and must be verified in the field before finalizing any job quote or contract. Service Provider makes no warranty as to measurement precision.
- Permit data depends on municipal reporting schedules. Cedar Rapids data is pulled daily. Expanded county coverage depends on availability of public permit portals.
- Storm lead scoring is automated based on NOAA alert severity. Client is responsible for qualifying leads before outreach.
- AI Follow-Up Agent drafts are for Client review only — Client approves all outreach before it sends. Service Provider is not liable for outreach content once Client approves and sends.

---

## 9. CONFIDENTIALITY

Both parties agree to keep the terms of this agreement and any proprietary business information confidential. Client agrees not to share Titan OS access credentials with competitors or third parties without written consent.

---

## 10. ENTIRE AGREEMENT

This document constitutes the entire agreement between the parties. No verbal commitments are binding unless added to this agreement in writing and signed by both parties.

---

**Service Provider Signature:** _______________________________  Date: ___________

**Client Signature:** _______________________________  Date: ___________

**Client Printed Name:** Landon Diehl

**Business:** Titan Consulting Contracting

---

*Questions before signing? Contact: _______________*
