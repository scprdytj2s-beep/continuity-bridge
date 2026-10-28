// lib/security.js  —  gedeelde helpers voor de serverless functions in /api
// (escaping, invoervalidatie, serials en activatietokens, GitHub-JSON-opslag).

const crypto = require('crypto');

// ── Escaping & invoer ────────────────────────────────────────────────────────
function escapeHtml(s) {
  return String(s ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

// Eén regel tekst: geen regeleinden/stuurtekens (die kunnen velden in een
// issue-body vervalsen), afgekapt op max tekens.
function cleanLine(s, max) {
  if (typeof s !== 'string') return '';
  return s.replace(/[\u0000-\u001f\u007f]+/g, ' ').trim().slice(0, max);
}

// Meerregelige tekst: regeleinden mogen, overige stuurtekens niet.
function cleanText(s, max) {
  if (typeof s !== 'string') return '';
  return s.replace(/[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f]/g, '').trim().slice(0, max);
}

function isEmail(s) {
  return typeof s === 'string' && s.length <= 254 &&
         /^[^\s@<>"',;:()\[\]\\]+@[^\s@<>"',;:()\[\]\\]+\.[A-Za-z]{2,}$/.test(s);
}

// ── Serials ──────────────────────────────────────────────────────────────────
// Formaat (ongewijzigd, zie ale_merger_gui.py): CB- + 24 base32-tekens =
// 2 bytes vervaldag (dagen sinds 2024-01-01) + 8 bytes naam + 5 bytes HMAC.
//
// Vanaf v1.5 is de HMAC-sleutel geheim: afgeleid van LIC_SIGNING_KEY, die alleen
// in Vercel staat. De app kan een serial dus niet meer zelf controleren; dat doet
// /api/activate, dat bij succes een Ed25519-getekend activatietoken teruggeeft
// (offline te controleren met de publieke sleutel die in de app zit).
//
// Oudere serials zijn getekend met de oude sleutel, die publiek in de repo stond
// (iedereen kon ermee serials maken). Die worden alleen nog geaccepteerd als ze
// op de lijst LEGACY_SERIALS (Vercel-env) staan.
const LIC_EPOCH_MS    = Date.UTC(2024, 0, 1);
const B32_ALPHA       = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ234567';
const LEGACY_HMAC_KEY = 'CB2026-ContBridge-HMAC-S3cr3t-K3y';

// 32-byte Ed25519-seed (base64) uit LIC_SIGNING_KEY, of null als die ontbreekt.
function signingSeed() {
  const seed = Buffer.from(process.env.LIC_SIGNING_KEY || '', 'base64');
  return seed.length === 32 ? seed : null;
}

function serialKey(seed) {
  return crypto.createHmac('sha256', seed).update('cb-serial-v2').digest();
}

function serialMac(key, payload) {
  return crypto.createHmac('sha256', key).update(payload).digest().subarray(0, 5);
}

function normalizeSerial(serial) {
  return String(serial || '').toUpperCase().replace(/[\s-]/g, '');
}

// De 24 base32-tekens zonder 'CB'-prefix — voor vergelijkingen tussen lijsten.
function serialCore(serial) {
  const clean = normalizeSerial(serial);
  return clean.startsWith('CB') ? clean.slice(2) : clean;
}

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

function base32decode(str) {
  let bits = 0, value = 0;
  const out = [];
  for (const ch of str) {
    const idx = B32_ALPHA.indexOf(ch);
    if (idx < 0) return null;
    value = (value << 5) | idx;
    bits += 5;
    if (bits >= 8) {
      bits -= 8;
      out.push((value >>> bits) & 0xff);
    }
  }
  return Buffer.from(out);
}

// Nieuwe serial, geldig t/m expiry (Date; standaard vandaag + 365 dagen).
function issueSerial(name, seed, expiry) {
  const expiryDays = expiry
    ? Math.floor((expiry.getTime() - LIC_EPOCH_MS) / 86400000)
    : Math.floor((Date.now() - LIC_EPOCH_MS) / 86400000) + 365;
  const daysBuf = Buffer.alloc(2);
  daysBuf.writeUInt16BE(expiryDays & 0xffff);

  const nameBuf = Buffer.alloc(8, 0);
  Buffer.from(String(name).trim(), 'utf8').subarray(0, 8).copy(nameBuf);

  const payload = Buffer.concat([daysBuf, nameBuf]);                 // 10 bytes
  const b32 = base32encode(Buffer.concat([payload, serialMac(serialKey(seed), payload)]));
  return `CB-${b32.match(/.{4}/g).join('-')}`;                       // 24 tekens
}

// Grandfathered serials van vóór v1.5 (komma/spatie/regel-gescheiden).
function legacyAllowed(core) {
  return (process.env.LEGACY_SERIALS || '')
    .split(/[\s,;]+/).filter(Boolean).map(serialCore).includes(core);
}

// Returns { ok, reason, expiry, name, legacy }
// reason: 'ongeldig' | 'verlopen' | 'niet_erkend' (oude serial, niet op de lijst)
function verifySerial(serial, seed) {
  const core = serialCore(serial);
  if (core.length !== 24) return { ok: false, reason: 'ongeldig' };
  const raw = base32decode(core);
  if (!raw || raw.length !== 15) return { ok: false, reason: 'ongeldig' };
  const payload = raw.subarray(0, 10);
  const sig     = raw.subarray(10, 15);

  let legacy = false;
  if (!crypto.timingSafeEqual(sig, serialMac(serialKey(seed), payload))) {
    if (!crypto.timingSafeEqual(sig, serialMac(LEGACY_HMAC_KEY, payload))) {
      return { ok: false, reason: 'ongeldig' };
    }
    if (!legacyAllowed(core)) return { ok: false, reason: 'niet_erkend' };
    legacy = true;
  }
  const name   = raw.subarray(2, 10).toString('utf8').replace(/\0+$/, '');
  const expiry = new Date(LIC_EPOCH_MS + raw.readUInt16BE(0) * 86400000);
  if (Date.now() >= expiry.getTime()) return { ok: false, reason: 'verlopen', expiry, name, legacy };
  return { ok: true, expiry, name, legacy };
}

// ── Activatietokens (Ed25519) ────────────────────────────────────────────────
// Token = 'cbt1.' + base64url(JSON-claims) + '.' + base64url(handtekening),
// getekend over alles vóór de laatste punt. De app (_token_verify) controleert
// de handtekening met de ingebakken publieke sleutel.
const PKCS8_ED25519_PREFIX = Buffer.from('302e020100300506032b657004220420', 'hex');

function signingPrivateKey(seed) {
  return crypto.createPrivateKey({
    key: Buffer.concat([PKCS8_ED25519_PREFIX, seed]), format: 'der', type: 'pkcs8',
  });
}

// Ruwe 32-byte publieke sleutel (hex) — deze staat als _LIC_PUBKEY in de app.
function signingPublicKeyHex(seed) {
  return crypto.createPublicKey(signingPrivateKey(seed))
    .export({ format: 'der', type: 'spki' }).subarray(-32).toString('hex');
}

function signActivationToken(claims, seed) {
  const signed = `cbt1.${Buffer.from(JSON.stringify(claims)).toString('base64url')}`;
  const sig = crypto.sign(null, Buffer.from(signed), signingPrivateKey(seed));
  return `${signed}.${sig.toString('base64url')}`;
}

// ── GitHub-contents als kleine JSON-opslag ───────────────────────────────────
async function ghRequest(method, url, token, body) {
  const r = await fetch(url, {
    method,
    headers: {
      Authorization:          `Bearer ${token}`,
      Accept:                 'application/vnd.github+json',
      'User-Agent':           'ContinuityBridge-Server',
      'X-GitHub-Api-Version': '2022-11-28',
      ...(body ? { 'Content-Type': 'application/json' } : {}),
    },
    body: body ? JSON.stringify(body) : undefined,
  });
  if (r.status === 404) return null;
  if (!r.ok) throw new Error(`GitHub ${r.status}: ${(await r.text()).slice(0, 200)}`);
  return r.json();
}

// Leest een JSON-array uit een repo-bestand. Returns { data, sha } —
// data = [] en sha = null als het bestand nog niet bestaat.
async function readJsonFile(repo, path, token) {
  const res = await ghRequest('GET', `https://api.github.com/repos/${repo}/contents/${path}`, token);
  if (!res) return { data: [], sha: null };
  return { data: JSON.parse(Buffer.from(res.content, 'base64').toString('utf8')), sha: res.sha };
}

async function writeJsonFile(repo, path, token, data, sha, message) {
  await ghRequest('PUT', `https://api.github.com/repos/${repo}/contents/${path}`, token, {
    message,
    content: Buffer.from(JSON.stringify(data, null, 2)).toString('base64'),
    ...(sha ? { sha } : {}),
  });
}

// Privé repo voor klant- en meldersgegevens — standaard nooit de publieke repo.
function privateRepo() {
  return process.env.LICENSES_REPO || 'scprdytj2s-beep/cb-licenses';
}

// ── Eenvoudige rate limit (per warme serverless-instantie, best effort) ──────
const _hits = new Map();
function rateLimited(key, max, windowMs) {
  const now  = Date.now();
  const list = (_hits.get(key) || []).filter(t => now - t < windowMs);
  list.push(now);
  _hits.set(key, list);
  if (_hits.size > 5000) _hits.clear();
  return list.length > max;
}

function clientIp(req) {
  return String(req.headers['x-forwarded-for'] || req.socket?.remoteAddress || '')
    .split(',')[0].trim();
}

module.exports = {
  escapeHtml, cleanLine, cleanText, isEmail,
  normalizeSerial, serialCore, verifySerial, issueSerial, signingSeed,
  signActivationToken, signingPublicKeyHex,
  LEGACY_HMAC_KEY, LIC_EPOCH_MS, serialMac, base32encode, base32decode,
  ghRequest, readJsonFile, writeJsonFile, privateRepo,
  rateLimited, clientIp,
};
