'use strict';
/**
 * GET /api/admin/jobs             — list all jobs
 * POST /api/admin/jobs            — create a job
 * PATCH /api/admin/jobs           — update a job { id, ...fields }
 * DELETE /api/admin/jobs          — delete a job { id }
 *
 * Mutations require CSRF header and only allowlisted fields are accepted.
 */
const { requireAdmin, requireCsrf } = require('../_admin-verify');
const { sbFetch } = require('../_supabase-admin');

const MAX_LIMIT = 200;

const ALLOWED_JOB_FIELDS = new Set([
  'name', 'address', 'phone', 'email', 'stage', 'value', 'source', 'notes',
  'insurance_co', 'claim_number', 'adjuster_name', 'adjuster_phone',
  'deductible', 'damage_type',
]);

const ALLOWED_STAGES = new Set(['lead', 'estimate', 'signed', 'production', 'collected']);

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

module.exports = async function handler(req, res) {
  if (await requireAdmin(req, res)) return;

  if (req.method === 'GET') {
    const rawLimit = parseInt(req.query?.limit, 10);
    const limit = Number.isFinite(rawLimit) && rawLimit > 0
      ? Math.min(rawLimit, MAX_LIMIT)
      : MAX_LIMIT;
    try {
      const rows = await sbFetch(
        `jobs?order=updated_at.desc&limit=${limit}` +
        `&select=id,name,address,phone,email,stage,value,source,notes,` +
        `insurance_co,claim_number,adjuster_name,adjuster_phone,deductible,damage_type,` +
        `created_at,updated_at`
      );
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
      const rows = await sbFetch('jobs', {
        method: 'POST',
        body: JSON.stringify(fields),
        headers: { Prefer: 'return=representation' },
      });
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
    if (!id || typeof id !== 'string' || !/^[a-zA-Z0-9_-]+$/.test(id)) {
      return res.status(400).json({ error: 'Valid id required' });
    }
    const fields = sanitizeJobFields(body);
    if (!Object.keys(fields).length) {
      return res.status(400).json({ error: 'No allowed fields to update' });
    }
    fields.updated_at = new Date().toISOString();
    try {
      await sbFetch(`jobs?id=eq.${encodeURIComponent(id)}`, {
        method: 'PATCH',
        body: JSON.stringify(fields),
        headers: { Prefer: 'return=minimal' },
      });
      return res.status(200).json({ ok: true });
    } catch (err) {
      console.error('[admin/jobs PATCH]', err.message);
      return res.status(500).json({ error: 'Failed to update job' });
    }
  }

  if (req.method === 'DELETE') {
    if (requireCsrf(req, res)) return;
    const id = (req.body || {}).id;
    if (!id || typeof id !== 'string' || !/^[a-zA-Z0-9_-]+$/.test(id)) {
      return res.status(400).json({ error: 'Valid id required' });
    }
    try {
      await sbFetch(`jobs?id=eq.${encodeURIComponent(id)}`, {
        method: 'DELETE',
        headers: { Prefer: 'return=minimal' },
      });
      return res.status(200).json({ ok: true });
    } catch (err) {
      console.error('[admin/jobs DELETE]', err.message);
      return res.status(500).json({ error: 'Failed to delete job' });
    }
  }

  return res.status(405).end();
};
