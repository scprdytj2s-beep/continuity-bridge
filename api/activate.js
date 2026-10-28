// api/activate.js  —  Vercel serverless function
// POST { serial, machine_uuid } → serial controleren, activatie registreren in de
// cb-licenses repo en een getekend activatietoken teruggeven:
//   { ok: true, token }            → app slaat token op, verder offline geldig
//   { ok: false, reason }          → definitief geweigerd (app blokkeert)
//   HTTP 5xx                       → storing (app gaat door in proefperiode)

const {
  normalizeSerial, serialCore, verifySerial, signingSeed, signActivationToken,
  readJsonFile, writeJsonFile, privateRepo, rateLimited, clientIp,
} = require('../lib/security');

const REVOKE_URL =
  'https://raw.githubusercontent.com/scprdytj2s-beep/continuity-bridge/main/revoked.json';

async function isRevoked(normalSerial) {
  try {
    const r = await fetch(REVOKE_URL, { headers: { 'User-Agent': 'ContinuityBridge-Activate' } });
    if (!r.ok) return false;
    const list = await r.json();
    return Array.isArray(list) && list.some(s => serialCore(s) === serialCore(normalSerial));
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

  const seed = signingSeed();
  if (!seed) {
    // Configuratiefout aan onze kant: 503 → app gaat door in de proefperiode
    console.error('LIC_SIGNING_KEY ontbreekt of is ongeldig');
    return res.status(503).json({ ok: false, reason: 'server_config' });
  }

  // Alleen echte, geldige serials registreren — anders kan iedereen willekeurige
  // tekst (of andermans serial met een verzonnen machine-ID) in de repo schrijven.
  const check = verifySerial(serial, seed);
  if (!check.ok) return res.status(200).json({ ok: false, reason: check.reason });

  const normalSerial = normalizeSerial(serial);
  if (await isRevoked(normalSerial)) {
    return res.status(200).json({ ok: false, reason: 'ingetrokken' });
  }

  // Bij een storing in de registratie toch een token geven (fail open): de
  // handtekening bindt het token al aan deze machine.
  const grant = (warning) => res.status(200).json({
    ok: true,
    token: signActivationToken({
      v:      1,
      serial: normalSerial,
      name:   check.name,
      exp:    check.expiry.toISOString().slice(0, 10),
      mid:    machine_uuid,
      iat:    new Date().toISOString(),
    }, seed),
    ...(warning ? { warning } : {}),
  });

  const token = process.env.GITHUB_TOKEN;
  if (!token) {
    console.warn('GITHUB_TOKEN not set, skipping activation check');
    return grant('no_token');
  }

  const repo = privateRepo();
  const path = 'data/activations.json';

  let sha, activations;
  try {
    ({ data: activations, sha } = await readJsonFile(repo, path, token));
  } catch (err) {
    console.error('GitHub read failed:', err.message);
    return grant('read_failed');
  }

  // Check: is serial al geactiveerd op een andere machine?
  const record = activations.find(a => a.serial === normalSerial);
  if (record) {
    if (record.machine_uuid === machine_uuid) {
      // Zelfde machine → heractivatie altijd OK
      return grant();
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
    return grant('write_failed');
  }

  return grant();
};
