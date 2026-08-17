'use strict';
/**
 * GET /api/admin/storm
 * Returns storm events ordered by onset_at desc.
 * Requires valid admin session cookie.
 */
const { requireAdmin } = require('../_admin-verify');
const { sbFetch } = require('../_supabase-admin');

const MAX_LIMIT = 100;

module.exports = async function handler(req, res) {
  if (req.method !== 'GET') return res.status(405).end();
  if (await requireAdmin(req, res)) return;

  const rawLimit = parseInt(req.query?.limit, 10);
  const limit = Number.isFinite(rawLimit) && rawLimit > 0
    ? Math.min(rawLimit, MAX_LIMIT)
    : MAX_LIMIT;

  try {
    const rows = await sbFetch(
      `storm_events?order=onset_at.desc&limit=${limit}&select=id,event_type,area_desc,counties,hail_size_inches,wind_gust_mph,score,onset_at,expires_at,source`
    );
    return res.status(200).json(Array.isArray(rows) ? rows : []);
  } catch (err) {
    console.error('[admin/storm]', err.message);
    return res.status(500).json({ error: 'Failed to load storm events' });
  }
};
