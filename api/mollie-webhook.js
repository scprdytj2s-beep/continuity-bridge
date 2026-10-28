// api/mollie-webhook.js  —  Vercel serverless function
// Mollie POST { id: 'tr_xxx' } → verify paid → serial → email → GitHub log

const { createMollieClient } = require('@mollie/api-client');
const { Resend } = require('resend');
const crypto = require('crypto');
const {
  escapeHtml, cleanLine, isEmail, readJsonFile, writeJsonFile, privateRepo,
} = require('../lib/security');

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

// ── GitHub license log (privé repo — klantgegevens nooit in de publieke repo) ─
const LICENSES_PATH = 'data/licenses.json';

function githubToken() {
  const token = process.env.GITHUB_TOKEN;
  return token && token !== 'STEL_MIJ_IN' ? token : null;
}

// Mollie roept de webhook bij retries meerdere keren aan voor dezelfde
// betaling — controleer of deze al verwerkt is (anders dubbele mails/serials).
async function alreadyProcessed(paymentId) {
  const token = githubToken();
  if (!token) return false;
  const { data } = await readJsonFile(privateRepo(), LICENSES_PATH, token);
  return data.some(e => e.paymentId === paymentId);
}

async function logToGitHub(entry) {
  const token = githubToken();
  if (!token) { console.warn('GITHUB_TOKEN not set'); return; }
  const repo = privateRepo();
  const { data, sha } = await readJsonFile(repo, LICENSES_PATH, token);
  data.push(entry);
  await writeJsonFile(repo, LICENSES_PATH, token, data, sha,
                      `license issued: ${entry.paymentId}`);
}

// ── Email ────────────────────────────────────────────────────────────────────
async function sendNotificationEmail(name, email, serial) {
  const resend = new Resend(process.env.RESEND_API_KEY);
  await resend.emails.send({
    from:    'Continuity Bridge <licentie@studiomichielboesveldt.nl>',
    to:      'support@studiomichielboesveldt.nl',
    subject: `🎉 Nieuwe licentie verkocht — ${cleanLine(name, 80)}`,
    html: `<p><strong>${escapeHtml(name)}</strong> (${escapeHtml(email)}) heeft zojuist een licentie gekocht.</p>
           <p>Serial: <code>${escapeHtml(serial)}</code></p>`,
  });
}

async function sendLicenseEmail(email, name, serial) {
  const resend = new Resend(process.env.RESEND_API_KEY);
  // Resend gooit niet bij een API-fout maar geeft { error } terug
  const { error } = await resend.emails.send({
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
  <h1>Bedankt, ${escapeHtml(name)}!</h1>
  <p class="sub">Je Continuity Bridge jaarlicentie is klaar voor gebruik.</p>
  <div class="serial-box">
    <div class="serial-label">Jouw seriënummer</div>
    <div class="serial">${escapeHtml(serial)}</div>
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
  if (error) throw new Error(`Resend: ${error.message || JSON.stringify(error)}`);
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

  const meta  = payment.metadata || {};
  const name  = cleanLine(meta.name, 80);
  const email = cleanLine(meta.email, 254);
  if (!name || !isEmail(email)) {
    console.error('Missing/invalid metadata on payment', paymentId);
    return res.status(200).send('OK (no metadata)');
  }

  try {
    if (await alreadyProcessed(paymentId)) return res.status(200).send('OK (already processed)');
  } catch (err) {
    // Kan niet controleren (bv. token verlopen) → toch uitleveren: liever in
    // het zeldzame geval een dubbele mail dan een klant zonder serial.
    console.error('Idempotency check failed:', err.message);
  }

  const serial    = generateSerial(name);
  const issuedAt  = new Date().toISOString();

  // Eerst de klantmail: mislukt die, dan 500 zodat Mollie het opnieuw probeert
  // (anders betaalt de klant maar krijgt nooit een serial).
  try {
    await sendLicenseEmail(email, name, serial);
  } catch (err) {
    console.error('License email failed:', err);
    return res.status(500).send('Email failed');
  }

  const [notifRes, ghRes] = await Promise.allSettled([
    sendNotificationEmail(name, email, serial),
    logToGitHub({ paymentId, name, email, serial, issuedAt }),
  ]);

  if (notifRes.status  === 'rejected') console.error('Notif email failed:', notifRes.reason);
  if (ghRes.status     === 'rejected') console.error('GitHub log failed:', ghRes.reason);

  return res.status(200).send('OK');
};
