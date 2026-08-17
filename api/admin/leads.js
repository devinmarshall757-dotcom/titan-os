'use strict';
/**
 * GET /api/admin/leads
 * Returns leads ordered by created_at desc.
 * Requires valid admin session cookie.
 */
const { requireAdmin } = require('../_admin-verify');
const { sbFetch } = require('../_supabase-admin');

const MAX_LIMIT = 200;

module.exports = async function handler(req, res) {
  if (req.method !== 'GET') return res.status(405).end();
  if (await requireAdmin(req, res)) return;

  const rawLimit = parseInt(req.query?.limit, 10);
  const limit = Number.isFinite(rawLimit) && rawLimit > 0
    ? Math.min(rawLimit, MAX_LIMIT)
    : MAX_LIMIT;

  try {
    const rows = await sbFetch(
      `leads?order=created_at.desc&limit=${limit}&select=id,name,phone,email,service,address,note,estimate_low,estimate_high,created_at`
    );
    return res.status(200).json(Array.isArray(rows) ? rows : []);
  } catch (err) {
    console.error('[admin/leads]', err.message);
    return res.status(500).json({ error: 'Failed to load leads' });
  }
};
