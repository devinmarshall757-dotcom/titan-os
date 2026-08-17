'use strict';
/**
 * POST /api/admin-auth
 *
 * Verifies ADMIN_PASSWORD (constant-time), issues a signed HMAC session token,
 * and sets it in HttpOnly + CSRF cookies. Rate-limited.
 *
 * Required env vars:
 *   ADMIN_PASSWORD       — plain-text password (server-side only, never exposed)
 *   ADMIN_TOKEN_SECRET   — HMAC signing secret; NOT the Supabase service key
 */

const crypto = require('crypto');
const { applyRateLimit } = require('./_rate-limit');

const ADMIN_PASSWORD = process.env.ADMIN_PASSWORD;
const TOKEN_SECRET = process.env.ADMIN_TOKEN_SECRET;
const SESSION_HOURS = 8;

function _makeToken() {
  const expires = Date.now() + SESSION_HOURS * 60 * 60 * 1000;
  const payload = String(expires);
  const sig = crypto
    .createHmac('sha256', TOKEN_SECRET)
    .update(payload)
    .digest('hex');
  return `${expires}.${sig}`;
}

function _makeCsrf() {
  return crypto.randomBytes(24).toString('hex');
}

module.exports = async function handler(req, res) {
  if (req.method !== 'POST') return res.status(405).end();

  // Rate-limit before doing any credential work
  if (await applyRateLimit(req, res, 'admin_auth')) return;

  if (!ADMIN_PASSWORD || !TOKEN_SECRET) {
    console.error('[admin-auth] ADMIN_PASSWORD or ADMIN_TOKEN_SECRET not configured');
    return res.status(503).json({ error: 'Admin not configured' });
  }

  const { password } = req.body || {};
  if (!password || typeof password !== 'string') {
    return res.status(401).json({ error: 'Unauthorized' });
  }

  // Constant-time comparison via HMAC normalisation — avoids same-length requirement
  const inputHash = crypto
    .createHmac('sha256', TOKEN_SECRET)
    .update(password)
    .digest();
  const expectedHash = crypto
    .createHmac('sha256', TOKEN_SECRET)
    .update(ADMIN_PASSWORD)
    .digest();

  if (!crypto.timingSafeEqual(inputHash, expectedHash)) {
    return res.status(401).json({ error: 'Unauthorized' });
  }

  const token = _makeToken();
  const csrf = _makeCsrf();
  const maxAge = SESSION_HOURS * 60 * 60;
  const isSecure =
    process.env.VERCEL_ENV === 'production' ||
    process.env.NODE_ENV === 'production';
  const secureFlag = isSecure ? 'Secure; ' : '';

  res.setHeader('Set-Cookie', [
    // HttpOnly — JS cannot read this; carries the session identity
    `admin_token=${token}; HttpOnly; ${secureFlag}SameSite=Strict; Path=/; Max-Age=${maxAge}`,
    // Non-HttpOnly — JS reads this to include in X-CSRF-Token header
    `csrf_token=${csrf}; ${secureFlag}SameSite=Strict; Path=/; Max-Age=${maxAge}`,
  ]);

  // Return token + csrf so existing JS that caches in sessionStorage still works
  // in DEMO_MODE. In production mode the cookie is the authoritative credential.
  return res.status(200).json({ token, csrf });
};
