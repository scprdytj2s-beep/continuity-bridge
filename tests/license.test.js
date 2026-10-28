// tests/license.test.js  —  node --test tests/
// Serials en activatietokens aan de serverkant (lib/security.js, api/activate.js).

const test   = require('node:test');
const assert = require('node:assert');
const crypto = require('crypto');
const {
  issueSerial, verifySerial, signActivationToken, signingPublicKeyHex,
} = require('../lib/security');

const SEED = crypto.randomBytes(32);
const LEGACY_KEY = 'CB2026-ContBridge-HMAC-S3cr3t-K3y';

// Zoals de oude, publieke _serial_generate in de app (keygen)
function legacySerial(name, expiry) {
  const days = Math.floor((expiry - Date.UTC(2024, 0, 1)) / 86400000);
  const payload = Buffer.alloc(10);
  payload.writeUInt16BE(days);
  Buffer.from(name, 'utf8').subarray(0, 8).copy(payload, 2);
  const sig = crypto.createHmac('sha256', LEGACY_KEY).update(payload).digest().subarray(0, 5);
  const alpha = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ234567';
  let bits = 0, value = 0, out = '';
  for (const b of Buffer.concat([payload, sig])) {
    value = (value << 8) | b; bits += 8;
    while (bits >= 5) { bits -= 5; out += alpha[(value >>> bits) & 31]; }
  }
  return `CB-${out.match(/.{4}/g).join('-')}`;
}

const nextYear = new Date(Date.UTC(new Date().getUTCFullYear() + 1, 5, 1));

test('nieuwe serial: zelfde formaat, verifieert alleen met de juiste sleutel', () => {
  const serial = issueSerial('Pieter Pietersen', SEED);
  assert.match(serial, /^CB(-[A-Z2-7]{4}){6}$/);
  const ok = verifySerial(serial, SEED);
  assert.equal(ok.ok, true);
  assert.equal(ok.name, 'Pieter P');
  assert.equal(ok.legacy, false);
  assert.equal(verifySerial(serial, crypto.randomBytes(32)).reason, 'ongeldig');
  // Ook zonder streepjes / in kleine letters
  assert.equal(verifySerial(serial.replace(/-/g, '').toLowerCase(), SEED).ok, true);
});

test('gemanipuleerde serial wordt geweigerd', () => {
  const serial = issueSerial('Test', SEED);
  const flipped = serial.slice(0, 5) + (serial[5] === 'A' ? 'B' : 'A') + serial.slice(6);
  assert.equal(verifySerial(flipped, SEED).reason, 'ongeldig');
  assert.equal(verifySerial('CB-1234', SEED).reason, 'ongeldig');
});

test('verlopen serial', () => {
  const serial = issueSerial('Oud', SEED, new Date(Date.UTC(2025, 0, 1)));
  assert.equal(verifySerial(serial, SEED).reason, 'verlopen');
});

test('keygen-serial met de oude publieke sleutel: alleen op de legacy-lijst', () => {
  const forged = legacySerial('Hacker', nextYear);
  delete process.env.LEGACY_SERIALS;
  assert.equal(verifySerial(forged, SEED).reason, 'niet_erkend');

  const real = legacySerial('Klant', nextYear);
  process.env.LEGACY_SERIALS = `${real.toLowerCase()}, CBAAAA`;
  const r = verifySerial(real, SEED);
  assert.equal(r.ok, true);
  assert.equal(r.legacy, true);
  assert.equal(verifySerial(forged, SEED).reason, 'niet_erkend');
  delete process.env.LEGACY_SERIALS;
});

test('activatietoken: handtekening klopt met de publieke sleutel', () => {
  const token = signActivationToken({ v: 1, serial: 'CBX', mid: 'M' }, SEED);
  const [prefix, body, sig] = token.split('.');
  assert.equal(prefix, 'cbt1');
  assert.deepEqual(JSON.parse(Buffer.from(body, 'base64url')), { v: 1, serial: 'CBX', mid: 'M' });
  const pub = crypto.createPublicKey({
    key: Buffer.concat([Buffer.from('302a300506032b6570032100', 'hex'),
                        Buffer.from(signingPublicKeyHex(SEED), 'hex')]),
    format: 'der', type: 'spki',
  });
  assert.equal(crypto.verify(null, Buffer.from(`${prefix}.${body}`), pub, Buffer.from(sig, 'base64url')), true);
});

// ── api/activate.js als handler ──────────────────────────────────────────────
function call(body) {
  const handler = require('../api/activate');
  return new Promise((resolve) => {
    const res = {
      statusCode: 200,
      status(c) { this.statusCode = c; return this; },
      json(o)   { resolve({ status: this.statusCode, body: o }); },
      send(t)   { resolve({ status: this.statusCode, body: t }); },
    };
    handler({ method: 'POST', body, headers: { 'x-forwarded-for': `10.0.0.${Math.random() * 250 | 0}` } }, res);
  });
}

test('activate: geen sleutel geconfigureerd → 503 (app gaat in proefperiode)', async () => {
  delete process.env.LIC_SIGNING_KEY;
  const r = await call({ serial: issueSerial('X', SEED), machine_uuid: 'ABC' });
  assert.equal(r.status, 503);
  assert.equal(r.body.reason, 'server_config');
});

test('activate: echte serial → token, keygen-serial → geweigerd', async () => {
  process.env.LIC_SIGNING_KEY = SEED.toString('base64');
  delete process.env.GITHUB_TOKEN;
  const good = await call({ serial: issueSerial('Anna', SEED), machine_uuid: 'UUID-1' });
  assert.equal(good.body.ok, true);
  const claims = JSON.parse(Buffer.from(good.body.token.split('.')[1], 'base64url'));
  assert.equal(claims.mid, 'UUID-1');
  assert.equal(claims.name, 'Anna');

  const bad = await call({ serial: legacySerial('Hacker', nextYear), machine_uuid: 'UUID-1' });
  assert.deepEqual(bad.body, { ok: false, reason: 'niet_erkend' });
  delete process.env.LIC_SIGNING_KEY;
});
