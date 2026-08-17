'use strict';
/**
 * Shared admin session verification.
 *
 * Cookie layout (both set at login):
 *   admin_token  — HttpOnly, Secure, SameSite=Strict — carries the signed HMAC token
 *   csrf_token   — readable by JS, Secure, SameSite=Strict — for X-CSRF-Token header
 *
 * Required env vars:
 *   ADMIN_TOKEN_SECRET     — HMAC signing secret. No fallback allowed.
 *   ADMIN_PRODUCTION_MODE  — "true" to route to real Supabase data.
 *
 * Usage in a route:
 *   if (await requireAdmin(req, res)) return;           // auth check
 *   if (isMutating(req) && requireCsrf(req, res)) return; // CSRF check
 */

const crypto = require('crypto');

const TOKEN_SECRET = process.env.ADMIN_TOKEN_SECRET;
const PRODUCTION_MODE =
  process.env.ADMIN_PRODUCTION_MODE === 'true' && !!TOKEN_SECRET;

function parseCookies(req) {
  const raw = req.headers?.cookie || '';
  const out = {};
  for (const pair of raw.split(';')) {
    const eq = pair.indexOf('=');
    if (eq < 1) continue;
    const k = pair.slice(0, eq).trim();
    const v = pair.slice(eq + 1).trim();
    try { out[k] = decodeURIComponent(v); } catch { out[k] = v; }
  }
  return out;
}

/**
 * Verify a token string. Throws on any failure.
 * Uses constant-time comparison for the HMAC signature.
 */
function verifyToken(token) {
  if (!TOKEN_SECRET) throw new Error('ADMIN_TOKEN_SECRET not configured');
  if (!token || typeof token !== 'string') throw new Error('Missing token');
  const dot = token.indexOf('.');
  if (dot < 1) throw new Error('Malformed token');

  const payload = token.slice(0, dot);
  const sig = token.slice(dot + 1);

  // Reject obviously bad sig to avoid timingSafeEqual length mismatch
  if (!/^[0-9a-f]{64}$/.test(sig)) throw new Error('Malformed signature');

  const expected = crypto
    .createHmac('sha256', TOKEN_SECRET)
    .update(payload)
    .digest('hex');

  if (!crypto.timingSafeEqual(Buffer.from(sig, 'hex'), Buffer.from(expected, 'hex'))) {
    throw new Error('Invalid signature');
  }

  const expires = parseInt(payload, 10);
  if (!Number.isFinite(expires) || Date.now() > expires) {
    throw new Error('Token expired');
  }
  return expires;
}

/**
 * Middleware: verify the admin_token cookie.
 * Returns true if auth failed and a 401 was already sent.
 */
async function requireAdmin(req, res) {
  if (!TOKEN_SECRET) {
    console.error('[admin-verify] ADMIN_TOKEN_SECRET not configured');
    res.status(503).json({ error: 'Admin not configured' });
    return true;
  }
  const cookies = parseCookies(req);
  try {
    verifyToken(cookies.admin_token);
  } catch (err) {
    res.status(401).json({ error: 'Authentication required' });
    return true;
  }
  return false;
}

/**
 * CSRF check for state-changing routes.
 * Double-submit cookie pattern: X-CSRF-Token header must match csrf_token cookie.
 * Returns true if CSRF failed and a 403 was already sent.
 */
function requireCsrf(req, res) {
  const cookies = parseCookies(req);
  const cookieCsrf = cookies.csrf_token;
  const headerCsrf = req.headers['x-csrf-token'];
  if (!cookieCsrf || !headerCsrf || cookieCsrf !== headerCsrf) {
    res.status(403).json({ error: 'CSRF token mismatch' });
    return true;
  }
  return false;
}

/** True only when ADMIN_PRODUCTION_MODE=true and ADMIN_TOKEN_SECRET is set. */
function isProductionMode() {
  return PRODUCTION_MODE;
}

module.exports = { requireAdmin, requireCsrf, isProductionMode, parseCookies, verifyToken };
