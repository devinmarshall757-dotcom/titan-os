'use strict';
/**
 * Server-side Supabase helper using the service-role key.
 * Import only in server API routes — never exposed to the browser.
 */

const SUPABASE_URL =
  process.env.SUPABASE_URL || 'https://yfscfuyxbluidykmpjod.supabase.co';
const SUPABASE_SERVICE_KEY = process.env.SUPABASE_SERVICE_KEY;

function _serviceHeaders() {
  if (!SUPABASE_SERVICE_KEY) {
    throw new Error('SUPABASE_SERVICE_KEY not configured — admin routes cannot operate');
  }
  return {
    apikey: SUPABASE_SERVICE_KEY,
    Authorization: `Bearer ${SUPABASE_SERVICE_KEY}`,
    'Content-Type': 'application/json',
    Prefer: 'return=representation',
  };
}

/**
 * Fetch from Supabase REST API using service-role credentials.
 * Throws on non-2xx responses with a sanitized message.
 */
async function sbFetch(path, opts = {}) {
  const url = `${SUPABASE_URL}/rest/v1/${path}`;
  let headers;
  try {
    headers = _serviceHeaders();
  } catch (err) {
    throw err;
  }
  const res = await fetch(url, {
    ...opts,
    headers: { ...headers, ...(opts.headers || {}) },
    signal: opts.signal ?? AbortSignal.timeout(10000),
  });
  if (!res.ok) {
    const body = await res.text().catch(() => '');
    console.error(`[supabase-admin] ${res.status} on ${path}:`, body.slice(0, 300));
    throw new Error(`Database error (${res.status})`);
  }
  const ct = res.headers.get('content-type') || '';
  return ct.includes('json') ? res.json() : res.text();
}

module.exports = { sbFetch, SUPABASE_URL };
