const crypto = require('crypto');

const ADMIN_PASSWORD = process.env.ADMIN_PASSWORD;
const TOKEN_SECRET = process.env.ADMIN_TOKEN_SECRET || process.env.SUPABASE_SERVICE_KEY;

function makeToken() {
  const expires = Date.now() + 8 * 60 * 60 * 1000; // 8 hours
  const payload = `${expires}`;
  const sig = crypto.createHmac('sha256', TOKEN_SECRET).update(payload).digest('hex');
  return `${expires}.${sig}`;
}

module.exports = async function handler(req, res) {
  if (req.method !== 'POST') return res.status(405).end();

  const { password } = req.body || {};
  if (!password || !ADMIN_PASSWORD) return res.status(401).json({ error: 'Unauthorized' });
  if (password !== ADMIN_PASSWORD) return res.status(401).json({ error: 'Unauthorized' });

  const token = makeToken();
  res.status(200).json({ token });
};
