'use strict';
/**
 * GET /api/admin/config
 * Non-authenticated. Returns whether production mode is active.
 * Production mode requires ADMIN_PRODUCTION_MODE=true AND ADMIN_TOKEN_SECRET on the server.
 * The browser cannot activate production mode — only the server env var controls it.
 */
const { isProductionMode } = require('../_admin-verify');

module.exports = function handler(req, res) {
  if (req.method !== 'GET') return res.status(405).end();
  return res.status(200).json({
    mode: isProductionMode() ? 'production' : 'demo',
    // Never expose env var names or values here
  });
};
