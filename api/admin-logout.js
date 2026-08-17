'use strict';
/**
 * POST /api/admin-logout
 * Clears admin session cookies.
 */
module.exports = function handler(req, res) {
  if (req.method !== 'POST') return res.status(405).end();
  res.setHeader('Set-Cookie', [
    'admin_token=; HttpOnly; SameSite=Strict; Path=/; Max-Age=0',
    'csrf_token=; SameSite=Strict; Path=/; Max-Age=0',
  ]);
  return res.status(200).json({ ok: true });
};
