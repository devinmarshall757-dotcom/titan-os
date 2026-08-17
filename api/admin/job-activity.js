'use strict';
/**
 * GET /api/admin/job-activity?jobId=<id>  — list activity for a job
 * POST /api/admin/job-activity            — add a note { jobId, note, author }
 */
const { requireAdmin, requireCsrf } = require('../_admin-verify');
const { sbFetch } = require('../_supabase-admin');

const MAX_NOTE_LEN = 2000;
const MAX_AUTHOR_LEN = 100;
const MAX_LIMIT = 100;

module.exports = async function handler(req, res) {
  if (await requireAdmin(req, res)) return;

  if (req.method === 'GET') {
    const jobId = req.query?.jobId;
    if (!jobId || typeof jobId !== 'string' || !/^[a-zA-Z0-9_-]+$/.test(jobId)) {
      return res.status(400).json({ error: 'Valid jobId required' });
    }
    try {
      const rows = await sbFetch(
        `job_activity?job_id=eq.${encodeURIComponent(jobId)}&order=created_at.asc&limit=${MAX_LIMIT}` +
        `&select=id,job_id,note,author,created_at`
      );
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
    const note = typeof body.note === 'string' ? body.note.slice(0, MAX_NOTE_LEN) : '';
    const author = typeof body.author === 'string' ? body.author.slice(0, MAX_AUTHOR_LEN) : 'Admin';

    if (!jobId || typeof jobId !== 'string' || !/^[a-zA-Z0-9_-]+$/.test(jobId)) {
      return res.status(400).json({ error: 'Valid jobId required' });
    }
    if (!note.trim()) return res.status(400).json({ error: 'note required' });

    try {
      const rows = await sbFetch('job_activity', {
        method: 'POST',
        body: JSON.stringify({ job_id: jobId, note: note.trim(), author }),
        headers: { Prefer: 'return=representation' },
      });
      return res.status(201).json(Array.isArray(rows) ? rows[0] : rows);
    } catch (err) {
      console.error('[admin/job-activity POST]', err.message);
      return res.status(500).json({ error: 'Failed to add activity' });
    }
  }

  return res.status(405).end();
};
