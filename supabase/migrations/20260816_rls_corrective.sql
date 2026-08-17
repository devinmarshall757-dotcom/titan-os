-- Titan OS — RLS corrective migration
-- Addresses the table-name mismatch in 20260816_rls_hardening.sql:
--   api/measure.js writes to `property_measurements`
--   the prior migration locked down `measurements` (different table)
-- This migration adds RLS to `property_measurements` and supersedes any
-- broad policies that allow anonymous access to private data.
--
-- DO NOT APPLY until admin routes are deployed and verified.
-- Review in Supabase SQL editor before running.

-- ── PROPERTY_MEASUREMENTS ──
-- This is the table written by api/measure.js (the public measurement cache).
-- Anon can INSERT (the public measure endpoint writes cache rows via service key).
-- Anon cannot SELECT (measurements may include address/lat/lng — treat as private).
-- Service role has full access.

ALTER TABLE public.property_measurements ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "pm_anon_select" ON public.property_measurements;
DROP POLICY IF EXISTS "pm_anon_all" ON public.property_measurements;
DROP POLICY IF EXISTS "pm_service_all" ON public.property_measurements;

CREATE POLICY "pm_service_all" ON public.property_measurements
  FOR ALL TO service_role
  USING (true) WITH CHECK (true);

-- ── MEASUREMENTS (legacy table name from prior migration) ──
-- If this table also exists, ensure it is locked down identically.
-- The DO block skips gracefully if the table does not exist.

DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM information_schema.tables
             WHERE table_schema = 'public' AND table_name = 'measurements') THEN
    EXECUTE 'ALTER TABLE public.measurements ENABLE ROW LEVEL SECURITY';
    EXECUTE 'DROP POLICY IF EXISTS "measurements_service_all" ON public.measurements';
    EXECUTE 'CREATE POLICY "measurements_service_all" ON public.measurements
               FOR ALL TO service_role USING (true) WITH CHECK (true)';
  END IF;
END;
$$;

-- ── REVOKE broad anon grants that may pre-date RLS ──
-- Remove any existing anon SELECT on private tables that should not be public.
-- These statements are safe to run even if no such grant exists.

REVOKE SELECT ON public.leads FROM anon;
REVOKE SELECT ON public.jobs FROM anon;
REVOKE SELECT ON public.job_activity FROM anon;
REVOKE SELECT ON public.permits FROM anon;
REVOKE SELECT ON public.storm_events FROM anon;
REVOKE SELECT ON public.property_measurements FROM anon;

-- ── SMOKE TEST QUERIES (run manually after applying) ──
-- Verify anon is denied on private tables:
--
--   SET ROLE anon;
--   SELECT count(*) FROM public.leads;            -- expect: ERROR (RLS denial)
--   SELECT count(*) FROM public.jobs;             -- expect: ERROR (RLS denial)
--   SELECT count(*) FROM public.job_activity;     -- expect: ERROR (RLS denial)
--   SELECT count(*) FROM public.property_measurements; -- expect: ERROR (RLS denial)
--   SELECT count(*) FROM public.permits;          -- expect: ERROR (RLS denial)
--   SELECT count(*) FROM public.storm_events;     -- expect: ERROR (RLS denial)
--   SELECT * FROM public.reviews WHERE approved = false; -- expect: 0 rows (not error — policy filters)
--   SELECT * FROM public.reviews WHERE approved = true;  -- expect: approved rows only
--   RESET ROLE;
--
-- Verify service role has full access:
--   SET ROLE service_role;
--   SELECT count(*) FROM public.leads;            -- expect: row count
--   RESET ROLE;
