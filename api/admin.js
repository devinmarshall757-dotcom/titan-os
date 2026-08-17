'use strict';
/**
 * Unified admin API handler — /api/admin/:resource
 * Replaces individual api/admin/*.js files to stay within Vercel Hobby function limit.
 *
 * Routes:
 *   GET  /api/admin/config
 *   GET  /api/admin/leads
 *   GET  /api/admin/permits
 *   GET  /api/admin/storm
 *   GET  /api/admin/measurements
 *   GET|PATCH|DELETE /api/admin/reviews
 *   GET|POST|PATCH|DELETE /api/admin/jobs
 *   GET|POST /api/admin/job-activity
 */

const { requireAdmin, requireCsrf, isProductionMode } = require('./_admin-verify');
const { sbFetch } = require('./_supabase-admin');

// ── config ───────────────────────────────────────────────────────────────────
function handleConfig(req, res) {
  if (req.method !== 'GET') return res.status(405).end();
  return res.status(200).json({ mode: isProductionMode() ? 'production' : 'demo' });
}

// ── leads ────────────────────────────────────────────────────────────────────
const LEADS_MAX = 200;
async function handleLeads(req, res) {
  if (req.method !== 'GET') return res.status(405).end();
  if (await requireAdmin(req, res)) return;
  const rawLimit = parseInt(req.query?.limit, 10);
  const limit = Number.isFinite(rawLimit) && rawLimit > 0 ? Math.min(rawLimit, LEADS_MAX) : LEADS_MAX;
  try {
    const rows = await sbFetch(`leads?order=created_at.desc&limit=${limit}&select=id,name,phone,email,service,address,note,estimate_low,estimate_high,created_at`);
    return res.status(200).json(Array.isArray(rows) ? rows : []);
  } catch (err) {
    console.error('[admin/leads]', err.message);
    return res.status(500).json({ error: 'Failed to load leads' });
  }
}

// ── permits ───────────────────────────────────────────────────────────────────
const PERMITS_MAX = 500;
const ALLOWED_CITIES = ['Cedar Rapids', 'Dubuque', 'Council Bluffs'];
async function handlePermits(req, res) {
  if (req.method !== 'GET') return res.status(405).end();
  if (await requireAdmin(req, res)) return;
  const rawLimit = parseInt(req.query?.limit, 10);
  const limit = Number.isFinite(rawLimit) && rawLimit > 0 ? Math.min(rawLimit, PERMITS_MAX) : PERMITS_MAX;
  let filters = 'order=score.desc,issued_date.desc';
  const city = req.query?.city;
  if (city && ALLOWED_CITIES.includes(city)) filters += `&city=eq.${encodeURIComponent(city)}`;
  const minScore = parseInt(req.query?.minScore, 10);
  if (Number.isFinite(minScore) && minScore >= 0 && minScore <= 100) filters += `&score=gte.${minScore}`;
  try {
    const rows = await sbFetch(`permits?${filters}&limit=${limit}&select=id,permit_number,address,city,county,state,permit_type,description,contractor,owner,value,issued_date,score,source`);
    return res.status(200).json(Array.isArray(rows) ? rows : []);
  } catch (err) {
    console.error('[admin/permits]', err.message);
    return res.status(500).json({ error: 'Failed to load permits' });
  }
}

// ── storm ─────────────────────────────────────────────────────────────────────
const STORM_MAX = 100;
async function handleStorm(req, res) {
  if (req.method !== 'GET') return res.status(405).end();
  if (await requireAdmin(req, res)) return;
  const rawLimit = parseInt(req.query?.limit, 10);
  const limit = Number.isFinite(rawLimit) && rawLimit > 0 ? Math.min(rawLimit, STORM_MAX) : STORM_MAX;
  try {
    const rows = await sbFetch(`storm_events?order=onset_at.desc&limit=${limit}&select=id,event_type,area_desc,counties,hail_size_inches,wind_gust_mph,score,onset_at,expires_at,source`);
    return res.status(200).json(Array.isArray(rows) ? rows : []);
  } catch (err) {
    console.error('[admin/storm]', err.message);
    return res.status(500).json({ error: 'Failed to load storm events' });
  }
}

// ── measurements ──────────────────────────────────────────────────────────────
const MEAS_MAX = 200;
async function handleMeasurements(req, res) {
  if (req.method !== 'GET') return res.status(405).end();
  if (await requireAdmin(req, res)) return;
  const rawLimit = parseInt(req.query?.limit, 10);
  const limit = Number.isFinite(rawLimit) && rawLimit > 0 ? Math.min(rawLimit, MEAS_MAX) : MEAS_MAX;
  try {
    const rows = await sbFetch(`property_measurements?order=created_at.desc&limit=${limit}&select=id,address,address_normalized,lat,lng,roof_area_sqft,roof_squares,estimated_stories,gutter_length,siding_area,complexity,confidence,found,measurement_method,manual_verification_required,gis_source,lidar_date,created_at`);
    return res.status(200).json(Array.isArray(rows) ? rows : []);
  } catch (err) {
    console.error('[admin/measurements]', err.message);
    return res.status(500).json({ error: 'Failed to load measurements' });
  }
}

// ── reviews ───────────────────────────────────────────────────────────────────
const REVIEWS_MAX = 200;
const ALLOWED_REVIEW_PATCH = new Set(['approved']);
async function handleReviews(req, res) {
  if (await requireAdmin(req, res)) return;
  if (req.method === 'GET') {
    const approved = req.query?.approved === 'true';
    const rawLimit = parseInt(req.query?.limit, 10);
    const limit = Number.isFinite(rawLimit) && rawLimit > 0 ? Math.min(rawLimit, REVIEWS_MAX) : REVIEWS_MAX;
    try {
      const rows = await sbFetch(`reviews?approved=eq.${approved}&order=created_at.desc&limit=${limit}&select=id,name,email,rating,service,review,approved,created_at`);
      return res.status(200).json(Array.isArray(rows) ? rows : []);
    } catch (err) {
      console.error('[admin/reviews GET]', err.message);
      return res.status(500).json({ error: 'Failed to load reviews' });
    }
  }
  if (req.method === 'PATCH') {
    if (requireCsrf(req, res)) return;
    const body = req.body || {};
    const id = body.id;
    if (!id || typeof id !== 'string' || !/^[a-zA-Z0-9_-]+$/.test(id)) return res.status(400).json({ error: 'Valid id required' });
    const patch = {};
    for (const [k, v] of Object.entries(body)) {
      if (k !== 'id' && ALLOWED_REVIEW_PATCH.has(k)) patch[k] = v;
    }
    if (!Object.keys(patch).length) return res.status(400).json({ error: 'No allowed fields to update' });
    try {
      await sbFetch(`reviews?id=eq.${encodeURIComponent(id)}`, { method: 'PATCH', body: JSON.stringify(patch), headers: { Prefer: 'return=minimal' } });
      return res.status(200).json({ ok: true });
    } catch (err) {
      console.error('[admin/reviews PATCH]', err.message);
      return res.status(500).json({ error: 'Failed to update review' });
    }
  }
  if (req.method === 'DELETE') {
    if (requireCsrf(req, res)) return;
    const id = (req.body || {}).id;
    if (!id || typeof id !== 'string' || !/^[a-zA-Z0-9_-]+$/.test(id)) return res.status(400).json({ error: 'Valid id required' });
    try {
      await sbFetch(`reviews?id=eq.${encodeURIComponent(id)}`, { method: 'DELETE', headers: { Prefer: 'return=minimal' } });
      return res.status(200).json({ ok: true });
    } catch (err) {
      console.error('[admin/reviews DELETE]', err.message);
      return res.status(500).json({ error: 'Failed to delete review' });
    }
  }
  return res.status(405).end();
}

// ── jobs ──────────────────────────────────────────────────────────────────────
const JOBS_MAX = 200;
const ALLOWED_JOB_FIELDS = new Set(['name','address','phone','email','stage','value','source','notes','insurance_co','claim_number','adjuster_name','adjuster_phone','deductible','damage_type','roof_squares','roof_sqft','measurement_confidence','measurement_source','updated_at']);
const ALLOWED_STAGES = new Set(['lead','estimate','signed','production','collected']);
function sanitizeJobFields(body) {
  const out = {};
  for (const [k, v] of Object.entries(body)) {
    if (!ALLOWED_JOB_FIELDS.has(k)) continue;
    if (k === 'stage' && !ALLOWED_STAGES.has(v)) continue;
    if (typeof v === 'string') out[k] = v.slice(0, 1000);
    else if (v === null || typeof v === 'number') out[k] = v;
  }
  return out;
}
async function handleJobs(req, res) {
  if (await requireAdmin(req, res)) return;
  if (req.method === 'GET') {
    const rawLimit = parseInt(req.query?.limit, 10);
    const limit = Number.isFinite(rawLimit) && rawLimit > 0 ? Math.min(rawLimit, JOBS_MAX) : JOBS_MAX;
    try {
      const rows = await sbFetch(`jobs?order=updated_at.desc&limit=${limit}&select=id,name,address,phone,email,stage,value,source,notes,insurance_co,claim_number,adjuster_name,adjuster_phone,deductible,damage_type,created_at,updated_at`);
      return res.status(200).json(Array.isArray(rows) ? rows : []);
    } catch (err) {
      console.error('[admin/jobs GET]', err.message);
      return res.status(500).json({ error: 'Failed to load jobs' });
    }
  }
  if (req.method === 'POST') {
    if (requireCsrf(req, res)) return;
    const fields = sanitizeJobFields(req.body || {});
    if (!fields.name) return res.status(400).json({ error: 'name required' });
    try {
      const rows = await sbFetch('jobs', { method: 'POST', body: JSON.stringify(fields), headers: { Prefer: 'return=representation' } });
      return res.status(201).json(Array.isArray(rows) ? rows[0] : rows);
    } catch (err) {
      console.error('[admin/jobs POST]', err.message);
      return res.status(500).json({ error: 'Failed to create job' });
    }
  }
  if (req.method === 'PATCH') {
    if (requireCsrf(req, res)) return;
    const body = req.body || {};
    const id = body.id;
    if (!id || typeof id !== 'string' || !/^[a-zA-Z0-9_-]+$/.test(id)) return res.status(400).json({ error: 'Valid id required' });
    const fields = sanitizeJobFields(body);
    if (!Object.keys(fields).length) return res.status(400).json({ error: 'No allowed fields to update' });
    fields.updated_at = new Date().toISOString();
    try {
      await sbFetch(`jobs?id=eq.${encodeURIComponent(id)}`, { method: 'PATCH', body: JSON.stringify(fields), headers: { Prefer: 'return=minimal' } });
      return res.status(200).json({ ok: true });
    } catch (err) {
      console.error('[admin/jobs PATCH]', err.message);
      return res.status(500).json({ error: 'Failed to update job' });
    }
  }
  if (req.method === 'DELETE') {
    if (requireCsrf(req, res)) return;
    const id = (req.body || {}).id;
    if (!id || typeof id !== 'string' || !/^[a-zA-Z0-9_-]+$/.test(id)) return res.status(400).json({ error: 'Valid id required' });
    try {
      await sbFetch(`jobs?id=eq.${encodeURIComponent(id)}`, { method: 'DELETE', headers: { Prefer: 'return=minimal' } });
      return res.status(200).json({ ok: true });
    } catch (err) {
      console.error('[admin/jobs DELETE]', err.message);
      return res.status(500).json({ error: 'Failed to delete job' });
    }
  }
  return res.status(405).end();
}

// ── job-activity ──────────────────────────────────────────────────────────────
const ACTIVITY_MAX = 100;
async function handleJobActivity(req, res) {
  if (await requireAdmin(req, res)) return;
  if (req.method === 'GET') {
    const jobId = req.query?.jobId;
    if (!jobId || typeof jobId !== 'string' || !/^[a-zA-Z0-9_-]+$/.test(jobId)) return res.status(400).json({ error: 'Valid jobId required' });
    try {
      const rows = await sbFetch(`job_activity?job_id=eq.${encodeURIComponent(jobId)}&order=created_at.asc&limit=${ACTIVITY_MAX}&select=id,job_id,note,author,created_at`);
      return res.status(200).json(Array.isArray(rows) ? rows : []);
    } catch (err) {
      console.error('[admin/job-activity GET]', err.message);
      return res.status(500).json({ error: 'Failed to load activity' });
    }
  }
  if (req.method === 'POST') {
    if (requireCsrf(req, res)) return;
    const body = req.body || {};
    const jobId = body.jobId;
    const note = typeof body.note === 'string' ? body.note.slice(0, 2000) : '';
    const author = typeof body.author === 'string' ? body.author.slice(0, 100) : 'Admin';
    if (!jobId || typeof jobId !== 'string' || !/^[a-zA-Z0-9_-]+$/.test(jobId)) return res.status(400).json({ error: 'Valid jobId required' });
    if (!note.trim()) return res.status(400).json({ error: 'note required' });
    try {
      const rows = await sbFetch('job_activity', { method: 'POST', body: JSON.stringify({ job_id: jobId, note: note.trim(), author }), headers: { Prefer: 'return=representation' } });
      return res.status(201).json(Array.isArray(rows) ? rows[0] : rows);
    } catch (err) {
      console.error('[admin/job-activity POST]', err.message);
      return res.status(500).json({ error: 'Failed to add activity' });
    }
  }
  return res.status(405).end();
}

// ── router ────────────────────────────────────────────────────────────────────
const ROUTES = {
  config:       handleConfig,
  leads:        handleLeads,
  permits:      handlePermits,
  storm:        handleStorm,
  measurements: handleMeasurements,
  reviews:      handleReviews,
  jobs:         handleJobs,
  'job-activity': handleJobActivity,
};

module.exports = async function handler(req, res) {
  // Path: /api/admin/leads  → req.query.resource = 'leads' (via vercel.json rewrite)
  const resource = (req.query?.resource || '').replace(/[^a-z-]/g, '');
  const handle = ROUTES[resource];
  if (!handle) return res.status(404).json({ error: `Unknown admin resource: ${resource}` });
  return handle(req, res);
};
