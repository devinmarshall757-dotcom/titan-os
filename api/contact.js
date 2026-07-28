module.exports = async function handler(req, res) {
  if (req.method !== 'POST') {
    return res.status(405).json({ error: 'Method not allowed' });
  }

  const { name, phone, email, service, message } = req.body;

  if (!name || !phone) {
    return res.status(400).json({ error: 'Name and phone are required' });
  }

  try {
    const response = await fetch('https://api.resend.com/emails', {
      method: 'POST',
      headers: {
        'Authorization': `Bearer ${process.env.RESEND_API_KEY}`,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        from: 'Titan Website <hello@titanconsultingcontracting.com>',
        to: ['Landon.diehl@titanconsultingcontracting.com'],
        subject: `New Estimate Request — ${name}`,
        html: `
          <div style="font-family:sans-serif;max-width:600px;margin:0 auto;padding:24px;">
            <h2 style="color:#131e38;margin-bottom:4px;">New Estimate Request</h2>
            <p style="color:#666;margin-top:0;">Submitted from titanconsultingcontracting.com</p>
            <hr style="border:none;border-top:1px solid #eee;margin:20px 0;">
            <table style="width:100%;border-collapse:collapse;">
              <tr><td style="padding:8px 0;color:#888;width:120px;">Name</td><td style="padding:8px 0;font-weight:600;">${name}</td></tr>
              <tr><td style="padding:8px 0;color:#888;">Phone</td><td style="padding:8px 0;font-weight:600;"><a href="tel:${phone}" style="color:#131e38;">${phone}</a></td></tr>
              ${email ? `<tr><td style="padding:8px 0;color:#888;">Email</td><td style="padding:8px 0;"><a href="mailto:${email}" style="color:#131e38;">${email}</a></td></tr>` : ''}
              ${service ? `<tr><td style="padding:8px 0;color:#888;">Service</td><td style="padding:8px 0;">${service}</td></tr>` : ''}
              ${message ? `<tr><td style="padding:8px 0;color:#888;vertical-align:top;">Message</td><td style="padding:8px 0;">${message}</td></tr>` : ''}
            </table>
            <hr style="border:none;border-top:1px solid #eee;margin:20px 0;">
            <p style="color:#888;font-size:13px;">Reply directly to this email or call the number above.</p>
          </div>
        `,
      }),
    });

    if (!response.ok) {
      const err = await response.json();
      console.error('Resend error:', err);
      return res.status(500).json({ error: 'Failed to send email' });
    }

    return res.status(200).json({ success: true });
  } catch (err) {
    console.error('Handler error:', err);
    return res.status(500).json({ error: 'Server error' });
  }
}
