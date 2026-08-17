'use strict';
/**
 * GET /api/admin/permits
 * Returns permits ordered by score desc, issued_date desc.
 * Supports ?city=Cedar+Rapids and ?minScore=80 filters.
 * Requires valid admin session cookie.
 */
const { requireAdmin } = require('../_admin-verify');
const { sbFetch } = require('../_supabase-admin');

const MAX_LIMIT = 500;
const ALLOWED_CITIES = ['Cedar Rapids', 'Dubuque', 'Council Bluffs'];

module.exports = async function handler(req, res) {
  if (req.method !== 'GET') return res.status(405).end();
  if (await requireAdmin(req, res)) return;

  const rawLimit = parseInt(req.query?.limit, 10);
  const limit = Number.isFinite(rawLimit) && rawLimit > 0
    ? Math.min(rawLimit, MAX_LIMIT)
    : MAX_LIMIT;

  let filters = 'order=score.desc,issued_date.desc';
  const city = req.query?.city;
  if (city && ALLOWED_CITIES.includes(city)) {
    filters += `&city=eq.${encodeURIComponent(city)}`;
  }
  const minScore = parseInt(req.query?.minScore, 10);
  if (Number.isFinite(minScore) && minScore >= 0 && minScore <= 100) {
    filters += `&score=gte.${minScore}`;
  }

  try {
    const rows = await sbFetch(
      `permits?${filters}&limit=${limit}&select=id,permit_number,address,city,county,state,permit_type,description,contractor,owner,value,issued_date,score,source`
    );
    return res.status(200).json(Array.isArray(rows) ? rows : []);
  } catch (err) {
    console.error('[admin/permits]', err.message);
    return res.status(500).json({ error: 'Failed to load permits' });
  }
};
