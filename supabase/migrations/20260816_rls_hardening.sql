-- Titan OS — RLS hardening migration
-- Run this in Supabase SQL editor. Review each policy before applying.
-- These policies lock down tables so only the service role can mutate data.
-- The publishable (anon) key gets read-only access to approved reviews only.

-- ── REVIEWS ──
ALTER TABLE public.reviews ENABLE ROW LEVEL SECURITY;

-- Public can only read approved reviews (for the website)
DROP POLICY IF EXISTS "reviews_public_read" ON public.reviews;
CREATE POLICY "reviews_public_read" ON public.reviews
  FOR SELECT TO anon
  USING (approved = true);

-- Service role has full access (scrapers, admin mutations go through service key)
DROP POLICY IF EXISTS "reviews_service_all" ON public.reviews;
CREATE POLICY "reviews_service_all" ON public.reviews
  FOR ALL TO service_role
  USING (true) WITH CHECK (true);

-- ── LEADS ──
ALTER TABLE public.leads ENABLE ROW LEVEL SECURITY;

-- Anon can INSERT only (lead capture form)
DROP POLICY IF EXISTS "leads_anon_insert" ON public.leads;
CREATE POLICY "leads_anon_insert" ON public.leads
  FOR INSERT TO anon
  WITH CHECK (true);

-- No anon SELECT — leads are private CRM data
DROP POLICY IF EXISTS "leads_service_all" ON public.leads;
CREATE POLICY "leads_service_all" ON public.leads
  FOR ALL TO service_role
  USING (true) WITH CHECK (true);

-- ── JOBS ──
ALTER TABLE public.jobs ENABLE ROW LEVEL SECURITY;

-- No public access — all mutations via service role only
DROP POLICY IF EXISTS "jobs_service_all" ON public.jobs;
CREATE POLICY "jobs_service_all" ON public.jobs
  FOR ALL TO service_role
  USING (true) WITH CHECK (true);

-- ── JOB ACTIVITY ──
ALTER TABLE public.job_activity ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "job_activity_service_all" ON public.job_activity;
CREATE POLICY "job_activity_service_all" ON public.job_activity
  FOR ALL TO service_role
  USING (true) WITH CHECK (true);

-- ── PERMITS ──
ALTER TABLE public.permits ENABLE ROW LEVEL SECURITY;

-- Service role only (scrapers write, admin reads)
DROP POLICY IF EXISTS "permits_service_all" ON public.permits;
CREATE POLICY "permits_service_all" ON public.permits
  FOR ALL TO service_role
  USING (true) WITH CHECK (true);

-- ── STORM EVENTS ──
ALTER TABLE public.storm_events ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "storm_events_service_all" ON public.storm_events;
CREATE POLICY "storm_events_service_all" ON public.storm_events
  FOR ALL TO service_role
  USING (true) WITH CHECK (true);

-- ── MEASUREMENTS ──
ALTER TABLE public.measurements ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "measurements_service_all" ON public.measurements;
CREATE POLICY "measurements_service_all" ON public.measurements
  FOR ALL TO service_role
  USING (true) WITH CHECK (true);

-- ── CLAUDE TASKS ──
ALTER TABLE public.claude_tasks ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "claude_tasks_service_all" ON public.claude_tasks;
CREATE POLICY "claude_tasks_service_all" ON public.claude_tasks
  FOR ALL TO service_role
  USING (true) WITH CHECK (true);

-- NOTE: The admin dashboard currently uses the publishable (anon) key for
-- all reads/writes. Until admin API routes are built behind the service key,
-- the dashboard will break on tables with RLS enabled for anon.
-- Apply this migration only when the admin is routing through authenticated
-- server endpoints, or add the service key to a backend proxy layer.
