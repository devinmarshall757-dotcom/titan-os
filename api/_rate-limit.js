'use strict';
/**
 * Rate limiter using Upstash Redis REST API (no npm packages — pure fetch).
 *
 * Required env vars:
 *   UPSTASH_REDIS_REST_URL    — Set to your Upstash Redis REST URL.
 *   UPSTASH_REDIS_REST_TOKEN  — Set to your Upstash REST token.
 *
 * Per-endpoint limits (comma-separated "requests,windowSeconds"):
 *   RATE_LIMIT_MEASURE      — /api/measure    (default: 10,60)
 *   RATE_LIMIT_CONTACT      — /api/contact    (default: 5,600)
 *   RATE_LIMIT_ADMIN_AUTH   — /api/admin-auth (default: 5,900)
 *
 * In production (VERCEL_ENV=production or NODE_ENV=production):
 *   - Missing Upstash config → fail closed (429/503).
 *   - Upstash unreachable → fail closed.
 * In development:
 *   - Missing Upstash config → warn + use in-memory fallback (not durable).
 *   - Upstash unreachable → warn + allow.
 */

const crypto = require('crypto');

const UPSTASH_URL = process.env.UPSTASH_REDIS_REST_URL;
const UPSTASH_TOKEN = process.env.UPSTASH_REDIS_REST_TOKEN;
const IS_PROD =
  process.env.VERCEL_ENV === 'production' ||
  process.env.NODE_ENV === 'production';

function parseLimit(envKey, defaultReqs, defaultSec) {
  const raw = process.env[envKey] || `${defaultReqs},${defaultSec}`;
  const parts = raw.split(',').map(Number);
  return {
    maxReqs: Number.isFinite(parts[0]) && parts[0] > 0 ? parts[0] : defaultReqs,
    windowSec: Number.isFinite(parts[1]) && parts[1] > 0 ? parts[1] : defaultSec,
  };
}

const LIMITS = {
  measure:    parseLimit('RATE_LIMIT_MEASURE',   10,  60),
  contact:    parseLimit('RATE_LIMIT_CONTACT',    5, 600),
  admin_auth: parseLimit('RATE_LIMIT_ADMIN_AUTH', 5, 900),
};

// In-memory dev fallback — not shared across serverless instances.
const _devBuckets = new Map();
let _devWarnedOnce = false;

function _devCheck(key, limit) {
  const now = Date.now();
  const windowMs = limit.windowSec * 1000;
  let entry = _devBuckets.get(key);
  if (!entry || now > entry.resetAt) {
    entry = { count: 0, resetAt: now + windowMs };
  }
  entry.count += 1;
  _devBuckets.set(key, entry);
  const remaining = Math.max(0, limit.maxReqs - entry.count);
  const retryAfter = Math.ceil((entry.resetAt - now) / 1000);
  return { allowed: entry.count <= limit.maxReqs, remaining, retryAfter };
}

async function _upstashCheck(key, limit) {
  const now = Date.now();
  const windowStart = now - limit.windowSec * 1000;
  // Sliding window via pipeline: add timestamp member, prune old, count, expire.
  const pipeline = [
    ['ZADD', key, 'NX', String(now), String(now)],
    ['ZREMRANGEBYSCORE', key, '0', String(windowStart)],
    ['ZCARD', key],
    ['PEXPIRE', key, String(limit.windowSec * 1000)],
  ];
  const res = await fetch(`${UPSTASH_URL}/pipeline`, {
    method: 'POST',
    headers: {
      Authorization: `Bearer ${UPSTASH_TOKEN}`,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(pipeline),
    signal: AbortSignal.timeout(3000),
  });
  if (!res.ok) throw new Error(`Upstash HTTP ${res.status}`);
  const data = await res.json();
  // Pipeline result index 2 = ZCARD response
  const cardResult = data[2];
  const count =
    typeof cardResult === 'object' && cardResult !== null
      ? cardResult.result ?? limit.maxReqs + 1
      : typeof cardResult === 'number'
      ? cardResult
      : limit.maxReqs + 1;
  const remaining = Math.max(0, limit.maxReqs - count);
  return { allowed: count <= limit.maxReqs, remaining, retryAfter: limit.windowSec };
}

/**
 * Hash the client IP so it is never stored or logged in plaintext.
 * Uses the first IP from X-Forwarded-For (Vercel is the trusted terminating proxy).
 */
function _hashedIp(req) {
  const xff = req.headers['x-forwarded-for'];
  const raw =
    (typeof xff === 'string' ? xff.split(',')[0].trim() : null) ||
    req.socket?.remoteAddress ||
    '0.0.0.0';
  return crypto.createHash('sha256').update(raw.trim()).digest('hex').slice(0, 20);
}

/**
 * Check the rate limit for the named endpoint.
 *
 * @param {import('http').IncomingMessage} req
 * @param {'measure'|'contact'|'admin_auth'} endpoint
 * @returns {Promise<{allowed: boolean, remaining: number, retryAfter: number, configMissing?: boolean}>}
 */
async function checkRateLimit(req, endpoint) {
  const limit = LIMITS[endpoint];
  if (!limit) throw new Error(`Unknown rate-limit endpoint: ${endpoint}`);

  const ip = _hashedIp(req);
  const key = `rl:titan:${endpoint}:${ip}`;

  if (!UPSTASH_URL || !UPSTASH_TOKEN) {
    if (IS_PROD) {
      console.error(
        `[rate-limit] UPSTASH_REDIS_REST_URL/TOKEN not set — failing closed in production (endpoint: ${endpoint})`
      );
      return { allowed: false, remaining: 0, retryAfter: 60, configMissing: true };
    }
    if (!_devWarnedOnce) {
      _devWarnedOnce = true;
      console.warn(
        '[rate-limit] DEV: Upstash not configured — using in-memory fallback. ' +
        'Set UPSTASH_REDIS_REST_URL + UPSTASH_REDIS_REST_TOKEN for production-accurate behaviour.'
      );
    }
    return _devCheck(key, limit);
  }

  try {
    return await _upstashCheck(key, limit);
  } catch (err) {
    console.error(`[rate-limit] Upstash error for ${endpoint}:`, err.message);
    if (IS_PROD) return { allowed: false, remaining: 0, retryAfter: 30 };
    // Dev: allow through if Upstash unreachable
    return { allowed: true, remaining: limit.maxReqs, retryAfter: 0 };
  }
}

/**
 * Express-style helper. Returns true if the request was rate-limited and a
 * 429 response was already sent. Caller should return immediately in that case.
 *
 * @param {import('http').IncomingMessage} req
 * @param {import('http').ServerResponse} res
 * @param {'measure'|'contact'|'admin_auth'} endpoint
 * @returns {Promise<boolean>}
 */
async function applyRateLimit(req, res, endpoint) {
  const limit = LIMITS[endpoint];
  let result;
  try {
    result = await checkRateLimit(req, endpoint);
  } catch (err) {
    console.error('[rate-limit] checkRateLimit threw:', err.message);
    result = IS_PROD
      ? { allowed: false, remaining: 0, retryAfter: 60 }
      : { allowed: true, remaining: limit?.maxReqs ?? 0, retryAfter: 0 };
  }

  res.setHeader('X-RateLimit-Limit', limit?.maxReqs ?? 0);
  res.setHeader('X-RateLimit-Remaining', result.remaining);

  if (!result.allowed) {
    res.setHeader('Retry-After', result.retryAfter);
    const msg = result.configMissing
      ? 'Service temporarily unavailable'
      : 'Too many requests';
    res.status(429).json({ error: msg, retryAfter: result.retryAfter });
    return true;
  }
  return false;
}

module.exports = { checkRateLimit, applyRateLimit, LIMITS };
