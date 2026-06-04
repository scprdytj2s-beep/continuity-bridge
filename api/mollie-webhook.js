// api/mollie-webhook.js  —  Vercel serverless function
// Mollie POST { id: 'tr_xxx' } → verify paid → serial → email → GitHub log

const { createMollieClient } = require('@mollie/api-client');
const { Resend } = require('resend');
const crypto = require('crypto');
const https = require('https');

// ── Serial generation ────────────────────────────────────────────────────────
const LIC_EPOCH = new Date('2024-01-01T00:00:00Z');
const B32_ALPHA  = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ234567';

function base32encode(buf) {
  let bits = 0, value = 0, output = '';
  for (const byte of buf) {
    value = (value << 8) | byte;
    bits += 8;
    while (bits >= 5) {
      bits -= 5;
      output += B32_ALPHA[(value >>> bits) & 0x1f];
    }
  }
  if (bits > 0) output += B32_ALPHA[(value << (5 - bits)) & 0x1f];
  return output;
}

function generateSerial(name) {
  // App verwacht VERVALDATUM (niet uitgiftedatum) in bytes 0-1
  const expiryDays = Math.floor((Date.now() - LIC_EPOCH.getTime()) / 86400000) + 365;
  const daysBuf = Buffer.alloc(2);
  daysBuf.writeUInt16BE(expiryDays & 0xffff);

  const nameBuf = Buffer.alloc(8, 0);
  Buffer.from(name.trim(), 'utf8').slice(0, 8).copy(nameBuf);

  const payload = Buffer.concat([daysBuf, nameBuf]); // 10 bytes
  const sig = crypto
    .createHmac('sha256', process.env.LIC_HMAC_KEY || 'CB2026-ContBridge-HMAC-S3cr3t-K3y')
    .update(payload)
    .digest()
    .slice(0, 5);

  const b32 = base32encode(Buffer.concat([payload, sig])); // 15 bytes → 24 chars
  return `CB-${b32.slice(0,4)}-${b32.slice(4,8)}-${b32.slice(8,12)}-${b32.slice(12,16)}-${b32.slice(16,20)}-${b32.slice(20,24)}`;
}

// ── GitHub license log ───────────────────────────────────────────────────────
function ghFetch(method, url, body, token) {
  return new Promise((resolve, reject) => {
    const opts = {
      method,
      headers: {
        Authorization:          `Bearer ${token}`,
        Accept:                 'application/vnd.github+json',
        'User-Agent':           'ContinuityBridge-Webhook',
        'Content-Type':         'application/json',
        'X-GitHub-Api-Version': '2022-11-28',
      },
    };
    const req = https.request(url, opts, (res) => {
      let data = '';
      res.on('data', d => data += d);
      res.on('end', () => {
        if (res.statusCode >= 400) return reject(new Error(`GitHub ${res.statusCode}: ${data}`));
        resolve(JSON.parse(data));
      });
    });
    req.on('error', reject);
    if (body) req.write(JSON.stringify(body));
    req.end();
  });
}

async function logToGitHub(entry) {
  const token = process.env.GITHUB_TOKEN;
  if (!token || token === 'STEL_MIJ_IN') { console.warn('GITHUB_TOKEN not set'); return; }
  // Gebruik LICENSES_REPO env var (stel in als private repo voor privacy klantdata)
  const repo  = process.env.LICENSES_REPO || 'scprdytj2s-beep/continuity-bridge';
  const path  = 'data/licenses.json';
  const api   = `https://api.github.com/repos/${repo}/contents/${path}`;

  let sha = null, existing = [];
  try {
    const res = await ghFetch('GET', api, null, token);
    sha = res.sha;
    existing = JSON.parse(Buffer.from(res.content, 'base64').toString('utf8'));
  } catch { /* file doesn't exist yet — start fresh */ }

  existing.push(entry);
  const content = Buffer.from(JSON.stringify(existing, null, 2)).toString('base64');
  await ghFetch('PUT', api, {
    message: `license issued: ${entry.email}`,
    content,
    ...(sha ? { sha } : {}),
  }, token);
}

// ── Email ────────────────────────────────────────────────────────────────────
async function sendNotificationEmail(name, email, serial) {
  const resend = new Resend(process.env.RESEND_API_KEY);
  await resend.emails.send({
    from:    'Continuity Bridge <licentie@studiomichielboesveldt.nl>',
    to:      'support@studiomichielboesveldt.nl',
    subject: `🎉 Nieuwe licentie verkocht — ${name}`,
    html: `<p><strong>${name}</strong> (${email}) heeft zojuist een licentie gekocht.</p>
           <p>Serial: <code>${serial}</code></p>`,
  });
}

async function sendLicenseEmail(email, name, serial) {
  const resend = new Resend(process.env.RESEND_API_KEY);
  await resend.emails.send({
    from:    'Continuity Bridge <licentie@studiomichielboesveldt.nl>',
    to:      email,
    subject: 'Je Continuity Bridge licentie',
    html: `<!DOCTYPE html>
<html lang="nl"><head><meta charset="utf-8"><style>
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;background:#0a0a0a;color:#e8e8e8;margin:0;padding:0}
.wrap{max-width:520px;margin:40px auto;padding:0 20px}
h1{font-size:22px;font-weight:600;color:#fff;margin-bottom:4px}
.sub{color:#888;font-size:14px;margin-bottom:32px}
.serial-box{background:#161616;border:1px solid #2a2a2a;border-radius:12px;padding:24px;text-align:center;margin:24px 0}
.serial-label{font-size:11px;letter-spacing:.12em;text-transform:uppercase;color:#666;margin-bottom:10px}
.serial{font-family:'SF Mono','Fira Code',monospace;font-size:17px;color:#d4a853;letter-spacing:.06em;word-break:break-all}
.steps{margin:28px 0}
.step{display:flex;gap:14px;margin-bottom:14px;align-items:flex-start}
.step-num{background:#d4a853;color:#000;border-radius:50%;width:22px;height:22px;display:flex;align-items:center;justify-content:center;font-size:12px;font-weight:700;flex-shrink:0}
.step-text{font-size:14px;color:#ccc;padding-top:2px}
.footer{font-size:12px;color:#555;margin-top:40px;border-top:1px solid #1a1a1a;padding-top:20px}
a{color:#d4a853;text-decoration:none}
</style></head>
<body><div class="wrap">
  <h1>Bedankt, ${name}!</h1>
  <p class="sub">Je Continuity Bridge jaarlicentie is klaar voor gebruik.</p>
  <div class="serial-box">
    <div class="serial-label">Jouw seriënummer</div>
    <div class="serial">${serial}</div>
  </div>
  <div class="steps">
    <div class="step"><div class="step-num">1</div><div class="step-text">Open Continuity Bridge op je Mac of Windows-pc.</div></div>
    <div class="step"><div class="step-num">2</div><div class="step-text">Ga naar <strong>Instellingen → Licentie activeren</strong>.</div></div>
    <div class="step"><div class="step-num">3</div><div class="step-text">Voer bovenstaand seriënummer in en klik op <strong>Activeer</strong>.</div></div>
  </div>
  <p style="font-size:14px;color:#999;">Bewaar deze e-mail — je hebt het seriënummer nodig bij een herinstallatie.
  Vragen? <a href="mailto:support@studiomichielboesveldt.nl">support@studiomichielboesveldt.nl</a>.</p>
  <div class="footer">Continuity Bridge · <a href="https://studiomichielboesveldt.nl/cbapp/">studiomichielboesveldt.nl/cbapp</a></div>
</div></body></html>`,
  });
}

// ── Handler ──────────────────────────────────────────────────────────────────
module.exports = async (req, res) => {
  if (req.method !== 'POST') return res.status(405).send('Method Not Allowed');

  // Mollie sends application/x-www-form-urlencoded; Vercel may leave it as string
  let body = req.body || {};
  if (typeof body === 'string') {
    body = Object.fromEntries(new URLSearchParams(body));
  }
  const paymentId = body.id;
  if (!paymentId) return res.status(400).send('No payment id');

  const mollie = createMollieClient({ apiKey: process.env.MOLLIE_API_KEY });

  let payment;
  try {
    payment = await mollie.payments.get(paymentId);
  } catch (err) {
    console.error('Mollie fetch error:', err);
    return res.status(502).send('Could not fetch payment');
  }

  if (payment.status !== 'paid') return res.status(200).send('OK (not paid)');

  const { name, email } = payment.metadata || {};
  if (!name || !email) {
    console.error('Missing metadata on payment', paymentId);
    return res.status(200).send('OK (no metadata)');
  }

  const serial    = generateSerial(name);
  const issuedAt  = new Date().toISOString();

  const [emailRes, notifRes, ghRes] = await Promise.allSettled([
    sendLicenseEmail(email, name, serial),
    sendNotificationEmail(name, email, serial),
    logToGitHub({ paymentId, name, email, serial, issuedAt }),
  ]);

  if (emailRes.status  === 'rejected') console.error('Email failed:', emailRes.reason);
  if (notifRes.status  === 'rejected') console.error('Notif email failed:', notifRes.reason);
  if (ghRes.status     === 'rejected') console.error('GitHub log failed:', ghRes.reason);

  return res.status(200).send('OK');
};
