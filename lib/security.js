// lib/security.js  —  gedeelde helpers voor de serverless functions in /api
// (escaping, invoervalidatie, serial-verificatie, GitHub-JSON-opslag).

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
// Zelfde formaat als _serial_generate/_serial_verify in ale_merger_gui.py:
// 2 bytes vervaldag (dagen sinds 2024-01-01) + 8 bytes naam + 5 bytes HMAC.
const LIC_EPOCH_MS = Date.UTC(2024, 0, 1);
const B32_ALPHA    = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ234567';

function licKey() {
  return process.env.LIC_HMAC_KEY || 'CB2026-ContBridge-HMAC-S3cr3t-K3y';
}

function normalizeSerial(serial) {
  return String(serial || '').toUpperCase().replace(/[\s-]/g, '');
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

// Returns { ok, reason, expiry } — reason: 'ongeldig' | 'verlopen'
function verifySerial(serial) {
  let clean = normalizeSerial(serial);
  if (clean.startsWith('CB')) clean = clean.slice(2);
  if (clean.length !== 24) return { ok: false, reason: 'ongeldig' };
  const raw = base32decode(clean);
  if (!raw || raw.length !== 15) return { ok: false, reason: 'ongeldig' };
  const payload  = raw.subarray(0, 10);
  const sig      = raw.subarray(10, 15);
  const expected = crypto.createHmac('sha256', licKey()).update(payload).digest().subarray(0, 5);
  if (!crypto.timingSafeEqual(sig, expected)) return { ok: false, reason: 'ongeldig' };
  const expiry = new Date(LIC_EPOCH_MS + raw.readUInt16BE(0) * 86400000);
  if (Date.now() >= expiry.getTime()) return { ok: false, reason: 'verlopen', expiry };
  return { ok: true, expiry };
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
  normalizeSerial, verifySerial,
  ghRequest, readJsonFile, writeJsonFile, privateRepo,
  rateLimited, clientIp,
};
