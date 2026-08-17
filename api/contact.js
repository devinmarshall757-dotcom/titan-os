const SUPABASE_URL = 'https://yfscfuyxbluidykmpjod.supabase.co';
const SUPABASE_KEY = process.env.SUPABASE_SERVICE_KEY || 'sb_publishable_DrqBo5ukYx-8hUOtDLISbQ_aFeG_A66';

module.exports = async function handler(req, res) {
  if (req.method !== 'POST') {
    return res.status(405).json({ error: 'Method not allowed' });
  }

  const { name, phone, email, service, message, measurement, address, estimate_low, estimate_high } = req.body;

  if (!name || !phone) {
    return res.status(400).json({ error: 'Name and phone are required' });
  }

  // Sanitize all user input before interpolating into HTML
  function he(s) {
    if (!s) return '';
    return String(s).slice(0, 1000)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;').replace(/'/g, '&#x27;');
  }
  const safeName    = he(name);
  const safePhone   = he(phone);
  const safeEmail   = he(email);
  const safeService = he(service);
  const safeMessage = he(message);

  // Save lead to Supabase — awaited so failures are caught before responding
  const dbRes = await fetch(`${SUPABASE_URL}/rest/v1/leads`, {
    method: 'POST',
    headers: {
      'apikey': SUPABASE_KEY,
      'Authorization': `Bearer ${SUPABASE_KEY}`,
      'Content-Type': 'application/json',
      'Prefer': 'return=minimal'
    },
    body: JSON.stringify({ name, phone, email: email || null, service: service || null, address: address || null, note: message || null, estimate_low: estimate_low || null, estimate_high: estimate_high || null })
  }).catch(e => { console.error('Supabase save failed:', e.message); return null; });
  if (!dbRes || !dbRes.ok) {
    console.error('Lead not saved to DB — status:', dbRes?.status);
  }

  const measureHtml = measurement ? `
    <hr style="border:none;border-top:1px solid #eee;margin:20px 0;">
    <h3 style="color:#131e38;margin-bottom:12px;">Property Measurements</h3>
    <table style="width:100%;border-collapse:collapse;">
      <tr><td style="padding:6px 0;color:#888;width:160px;">Address</td><td style="padding:6px 0;font-weight:600;">${measurement.address}</td></tr>
      <tr><td style="padding:6px 0;color:#888;">Roof Area</td><td style="padding:6px 0;">${measurement.roof_area_sqft?.toLocaleString()} sq ft (${measurement.roof_squares} squares)</td></tr>
      <tr><td style="padding:6px 0;color:#888;">Stories</td><td style="padding:6px 0;">${measurement.estimated_stories}</td></tr>
      <tr><td style="padding:6px 0;color:#888;">Gutter Length</td><td style="padding:6px 0;">${measurement.gutter_length?.toLocaleString()} ft</td></tr>
      <tr><td style="padding:6px 0;color:#888;">Siding Area</td><td style="padding:6px 0;">${measurement.siding_area?.toLocaleString()} sq ft</td></tr>
      <tr><td style="padding:6px 0;color:#888;">Roof Complexity</td><td style="padding:6px 0;">${measurement.complexity}</td></tr>
      <tr><td style="padding:6px 0;color:#888;">Pitch Estimate</td><td style="padding:6px 0;">${measurement.estimated_pitch}</td></tr>
      <tr><td style="padding:6px 0;color:#888;">Confidence</td><td style="padding:6px 0;">${measurement.confidence}%</td></tr>
    </table>` : '';

  const homeownerMeasureHtml = measurement ? `
    <div style="background:#f8f9fa;border-radius:12px;padding:20px;margin:20px 0;">
      <h3 style="color:#131e38;margin:0 0 14px;">Your Property Measurements</h3>
      <table style="width:100%;border-collapse:collapse;">
        <tr><td style="padding:6px 0;color:#666;width:160px;">Roof Area</td><td style="padding:6px 0;font-weight:600;">${measurement.roof_area_sqft?.toLocaleString()} sq ft</td></tr>
        <tr><td style="padding:6px 0;color:#666;">Roofing Squares</td><td style="padding:6px 0;font-weight:600;">${measurement.roof_squares}</td></tr>
        <tr><td style="padding:6px 0;color:#666;">Stories</td><td style="padding:6px 0;">${measurement.estimated_stories}</td></tr>
        <tr><td style="padding:6px 0;color:#666;">Gutter Perimeter</td><td style="padding:6px 0;">${measurement.gutter_length?.toLocaleString()} ft</td></tr>
        <tr><td style="padding:6px 0;color:#666;">Siding Area</td><td style="padding:6px 0;">${measurement.siding_area?.toLocaleString()} sq ft</td></tr>
        <tr><td style="padding:6px 0;color:#666;">Roof Complexity</td><td style="padding:6px 0;">${measurement.complexity}</td></tr>
      </table>
      <p style="color:#888;font-size:12px;margin:12px 0 0;">Sourced from US Census &amp; OpenStreetMap property data. These are estimates — your free on-site inspection will confirm exact measurements.</p>
    </div>` : '';

  try {
    const emails = [];

    // Landon notification
    emails.push(fetch('https://api.resend.com/emails', {
      method: 'POST',
      headers: {
        'Authorization': `Bearer ${process.env.RESEND_API_KEY}`,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        from: 'Titan Website <hello@titanconsultingcontracting.com>',
        to: ['Landon.diehl@titanconsultingcontracting.com'],
        subject: `New Estimate Request — ${safeName}`,
        html: `
          <div style="font-family:sans-serif;max-width:600px;margin:0 auto;padding:24px;">
            <h2 style="color:#131e38;margin-bottom:4px;">New Estimate Request</h2>
            <p style="color:#666;margin-top:0;">Submitted from titanconsultingcontracting.com</p>
            <hr style="border:none;border-top:1px solid #eee;margin:20px 0;">
            <table style="width:100%;border-collapse:collapse;">
              <tr><td style="padding:8px 0;color:#888;width:120px;">Name</td><td style="padding:8px 0;font-weight:600;">${safeName}</td></tr>
              <tr><td style="padding:8px 0;color:#888;">Phone</td><td style="padding:8px 0;font-weight:600;">${safePhone}</td></tr>
              ${safeEmail ? `<tr><td style="padding:8px 0;color:#888;">Email</td><td style="padding:8px 0;">${safeEmail}</td></tr>` : ''}
              ${safeService ? `<tr><td style="padding:8px 0;color:#888;">Service</td><td style="padding:8px 0;">${safeService}</td></tr>` : ''}
              ${safeMessage ? `<tr><td style="padding:8px 0;color:#888;vertical-align:top;">Details</td><td style="padding:8px 0;white-space:pre-line;">${safeMessage}</td></tr>` : ''}
            </table>
            ${measureHtml}
            <hr style="border:none;border-top:1px solid #eee;margin:20px 0;">
            <p style="color:#888;font-size:13px;">Reply directly to this email or call the number above.</p>
          </div>
        `,
      }),
    }));

    // Homeowner report (only if email provided)
    if (email) {
      emails.push(fetch('https://api.resend.com/emails', {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${process.env.RESEND_API_KEY}`,
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          from: 'Titan Consulting Contracting <hello@titanconsultingcontracting.com>',
          to: [email],
          subject: `Your ${service || 'Project'} Estimate from Titan Consulting`,
          html: `
            <div style="font-family:sans-serif;max-width:600px;margin:0 auto;padding:24px;">
              <div style="background:#0d1526;border-radius:12px;padding:24px;margin-bottom:20px;">
                <h1 style="color:#fff;margin:0 0 4px;font-size:22px;">Titan Consulting Contracting</h1>
                <p style="color:#60a5fa;margin:0;font-size:13px;">Cedar Rapids, IA · Licensed &amp; Insured</p>
              </div>
              <h2 style="color:#131e38;">Hi ${name},</h2>
              <p style="color:#444;">Thanks for requesting an estimate! Here's a summary of your project details and property measurements.</p>
              <div style="background:#f8f9fa;border-radius:12px;padding:20px;margin:20px 0;">
                <h3 style="color:#131e38;margin:0 0 12px;">Your Request</h3>
                <table style="width:100%;border-collapse:collapse;">
                  <tr><td style="padding:6px 0;color:#666;width:120px;">Service</td><td style="padding:6px 0;font-weight:600;">${service || 'General'}</td></tr>
                  <tr><td style="padding:6px 0;color:#666;">Phone</td><td style="padding:6px 0;">${phone}</td></tr>
                </table>
              </div>
              ${homeownerMeasureHtml}
              <div style="background:#0d1526;border-radius:12px;padding:20px;margin:20px 0;text-align:center;">
                <p style="color:#60a5fa;margin:0 0 8px;font-size:13px;font-weight:600;">NEXT STEP</p>
                <p style="color:#fff;margin:0;font-size:16px;">We'll reach out shortly to schedule your <strong>free on-site estimate</strong>. No obligation, same-day turnaround.</p>
              </div>
              <p style="color:#888;font-size:13px;">Questions? Reply to this email or call us directly.</p>
              <p style="color:#aaa;font-size:12px;">© 2025 Titan Consulting Contracting · Cedar Rapids, IA</p>
            </div>
          `,
        }),
      }));
    }

    const results = await Promise.allSettled(emails);
    const failed = results.filter(r => r.status === 'rejected');
    if (failed.length === emails.length) {
      console.error('All emails failed');
      return res.status(500).json({ error: 'Failed to send email' });
    }

    return res.status(200).json({ success: true });
  } catch (err) {
    console.error('Handler error:', err);
    return res.status(500).json({ error: 'Server error' });
  }
}
