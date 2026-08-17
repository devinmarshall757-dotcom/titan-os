'use strict';
/**
 * GET /api/admin/reviews          — list pending reviews (approved=false)
 * GET /api/admin/reviews?approved=true — list approved reviews
 * PATCH /api/admin/reviews        — approve a review { id, approved: true }
 * DELETE /api/admin/reviews       — delete a review { id }
 *
 * All mutations require CSRF header. Allowlisted fields only.
 */
const { requireAdmin, requireCsrf } = require('../_admin-verify');
const { sbFetch } = require('../_supabase-admin');

const MAX_LIMIT = 200;
const ALLOWED_PATCH_FIELDS = new Set(['approved']);

module.exports = async function handler(req, res) {
  if (await requireAdmin(req, res)) return;

  if (req.method === 'GET') {
    const approved = req.query?.approved === 'true';
    const rawLimit = parseInt(req.query?.limit, 10);
    const limit = Number.isFinite(rawLimit) && rawLimit > 0
      ? Math.min(rawLimit, MAX_LIMIT)
      : MAX_LIMIT;

    try {
      const rows = await sbFetch(
        `reviews?approved=eq.${approved}&order=created_at.desc&limit=${limit}` +
        `&select=id,name,email,rating,service,review,approved,created_at`
      );
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
    if (!id || typeof id !== 'string' || !/^[a-zA-Z0-9_-]+$/.test(id)) {
      return res.status(400).json({ error: 'Valid id required' });
    }
    const patch = {};
    for (const [k, v] of Object.entries(body)) {
      if (k === 'id') continue;
      if (!ALLOWED_PATCH_FIELDS.has(k)) continue;
      patch[k] = v;
    }
    if (!Object.keys(patch).length) {
      return res.status(400).json({ error: 'No allowed fields to update' });
    }
    try {
      await sbFetch(`reviews?id=eq.${encodeURIComponent(id)}`, {
        method: 'PATCH',
        body: JSON.stringify(patch),
        headers: { Prefer: 'return=minimal' },
      });
      return res.status(200).json({ ok: true });
    } catch (err) {
      console.error('[admin/reviews PATCH]', err.message);
      return res.status(500).json({ error: 'Failed to update review' });
    }
  }

  if (req.method === 'DELETE') {
    if (requireCsrf(req, res)) return;
    const body = req.body || {};
    const id = body.id;
    if (!id || typeof id !== 'string' || !/^[a-zA-Z0-9_-]+$/.test(id)) {
      return res.status(400).json({ error: 'Valid id required' });
    }
    try {
      await sbFetch(`reviews?id=eq.${encodeURIComponent(id)}`, {
        method: 'DELETE',
        headers: { Prefer: 'return=minimal' },
      });
      return res.status(200).json({ ok: true });
    } catch (err) {
      console.error('[admin/reviews DELETE]', err.message);
      return res.status(500).json({ error: 'Failed to delete review' });
    }
  }

  return res.status(405).end();
};
