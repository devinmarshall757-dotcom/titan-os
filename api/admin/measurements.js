'use strict';
/**
 * GET /api/admin/measurements
 * Returns property measurement records ordered by created_at desc.
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

  // Table may be property_measurements (api/measure.js uses this name)
  const table = 'property_measurements';

  try {
    const rows = await sbFetch(
      `${table}?order=created_at.desc&limit=${limit}` +
      `&select=id,address,address_normalized,lat,lng,roof_area_sqft,roof_squares,` +
      `estimated_stories,gutter_length,siding_area,complexity,confidence,found,` +
      `measurement_method,manual_verification_required,gis_source,lidar_date,created_at`
    );
    return res.status(200).json(Array.isArray(rows) ? rows : []);
  } catch (err) {
    console.error('[admin/measurements]', err.message);
    return res.status(500).json({ error: 'Failed to load measurements' });
  }
};
