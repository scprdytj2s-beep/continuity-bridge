// api/activate.js  —  Vercel serverless function
// POST { serial, machine_uuid } → check/register activation in cb-licenses repo

const {
  normalizeSerial, verifySerial, readJsonFile, writeJsonFile, privateRepo,
  rateLimited, clientIp,
} = require('../lib/security');

const REVOKE_URL =
  'https://raw.githubusercontent.com/scprdytj2s-beep/continuity-bridge/main/revoked.json';

async function isRevoked(normalSerial) {
  try {
    const r = await fetch(REVOKE_URL, { headers: { 'User-Agent': 'ContinuityBridge-Activate' } });
    if (!r.ok) return false;
    const list = await r.json();
    return Array.isArray(list) && list.some(s => normalizeSerial(s) === normalSerial);
  } catch {
    return false;   // lijst onbereikbaar → niet blokkeren
  }
}

module.exports = async (req, res) => {
  // De app doet een directe POST; geen browser-toegang nodig
  if (req.method !== 'POST') return res.status(405).send('Method Not Allowed');

  if (rateLimited(`act:${clientIp(req)}`, 20, 10 * 60 * 1000)) {
    return res.status(429).json({ ok: false, reason: 'te_veel_pogingen' });
  }

  let body = req.body || {};
  if (typeof body === 'string') {
    try { body = JSON.parse(body); } catch { body = {}; }
  }

  const { serial, machine_uuid } = body;
  if (typeof serial !== 'string' || typeof machine_uuid !== 'string' ||
      !/^[A-Za-z0-9-]{1,64}$/.test(machine_uuid)) {
    return res.status(400).json({ ok: false, reason: 'missing_data' });
  }

  // Alleen echte, geldige serials registreren — anders kan iedereen willekeurige
  // tekst (of andermans serial met een verzonnen machine-ID) in de repo schrijven.
  const check = verifySerial(serial);
  if (!check.ok) return res.status(200).json({ ok: false, reason: check.reason });

  const normalSerial = normalizeSerial(serial);
  if (await isRevoked(normalSerial)) {
    return res.status(200).json({ ok: false, reason: 'ingetrokken' });
  }

  const token = process.env.GITHUB_TOKEN;
  if (!token) {
    // Geen token → fail open (blokkeer gebruiker niet)
    console.warn('GITHUB_TOKEN not set, skipping activation check');
    return res.status(200).json({ ok: true, warning: 'no_token' });
  }

  const repo = privateRepo();
  const path = 'data/activations.json';

  let sha, activations;
  try {
    ({ data: activations, sha } = await readJsonFile(repo, path, token));
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

  try {
    await writeJsonFile(repo, path, token, activations, sha,
                        `activate: ${normalSerial.slice(0, 7)}…`);
  } catch (err) {
    console.error('GitHub write failed:', err.message);
    // Schrijven mislukt → toch toestaan (gebruiker is dan dubbel geregistreerd bij retry)
    return res.status(200).json({ ok: true, warning: 'write_failed' });
  }

  return res.status(200).json({ ok: true });
};
