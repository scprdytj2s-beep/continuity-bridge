// api/activate.js  —  Vercel serverless function
// POST { serial, machine_uuid } → check/register activation in cb-licenses repo

const https = require('https');

function ghFetch(method, url, body, token) {
  return new Promise((resolve, reject) => {
    const opts = {
      method,
      headers: {
        Authorization:          `Bearer ${token}`,
        Accept:                 'application/vnd.github+json',
        'User-Agent':           'ContinuityBridge-Activate',
        'Content-Type':         'application/json',
        'X-GitHub-Api-Version': '2022-11-28',
      },
    };
    const req = https.request(url, opts, (res) => {
      let data = '';
      res.on('data', d => data += d);
      res.on('end', () => {
        if (res.statusCode === 404) return resolve(null);
        if (res.statusCode >= 400) return reject(new Error(`GitHub ${res.statusCode}: ${data}`));
        resolve(JSON.parse(data));
      });
    });
    req.on('error', reject);
    if (body) req.write(JSON.stringify(body));
    req.end();
  });
}

module.exports = async (req, res) => {
  // CORS – app maakt directe fetch, geen browser nodig, maar voor de zekerheid
  res.setHeader('Access-Control-Allow-Origin', '*');
  if (req.method === 'OPTIONS') return res.status(200).end();
  if (req.method !== 'POST') return res.status(405).send('Method Not Allowed');

  let body = req.body || {};
  if (typeof body === 'string') {
    try { body = JSON.parse(body); } catch { body = {}; }
  }

  const { serial, machine_uuid } = body;
  if (!serial || !machine_uuid) {
    return res.status(400).json({ ok: false, reason: 'missing_data' });
  }

  const token = process.env.GITHUB_TOKEN;
  if (!token) {
    // Geen token → fail open (blokkeer gebruiker niet)
    console.warn('GITHUB_TOKEN not set, skipping activation check');
    return res.status(200).json({ ok: true, warning: 'no_token' });
  }

  const repo = process.env.LICENSES_REPO || 'scprdytj2s-beep/cb-licenses';
  const path = 'data/activations.json';
  const api  = `https://api.github.com/repos/${repo}/contents/${path}`;

  const normalSerial = serial.toUpperCase().replace(/[\s-]/g, '');

  let sha = null, activations = [];
  try {
    const existing = await ghFetch('GET', api, null, token);
    if (existing) {
      sha         = existing.sha;
      activations = JSON.parse(Buffer.from(existing.content, 'base64').toString('utf8'));
    }
  } catch (err) {
    console.error('GitHub read failed:', err.message);
    // Kan niet lezen → fail open
    return res.status(200).json({ ok: true, warning: 'read_failed' });
  }

  // Check: is serial al geactiveerd op een andere machine?
  const record = activations.find(a => a.serial === normalSerial);
  if (record) {
    if (record.machine_uuid === machine_uuid) {
      // Zelfde machine → heractivatie altijd OK
      return res.status(200).json({ ok: true });
    } else {
      // Andere machine → geblokkeerd
      return res.status(200).json({ ok: false, reason: 'al_gebonden' });
    }
  }

  // Nieuwe activatie — registreer
  activations.push({
    serial:       normalSerial,
    machine_uuid,
    activated_at: new Date().toISOString(),
  });

  const content = Buffer.from(JSON.stringify(activations, null, 2)).toString('base64');
  try {
    await ghFetch('PUT', api, {
      message: `activate: ${normalSerial.slice(0, 7)}…`,
      content,
      ...(sha ? { sha } : {}),
    }, token);
  } catch (err) {
    console.error('GitHub write failed:', err.message);
    // Schrijven mislukt → toch toestaan (gebruiker is dan dubbel geregistreerd bij retry)
    return res.status(200).json({ ok: true, warning: 'write_failed' });
  }

  return res.status(200).json({ ok: true });
};
