#!/usr/bin/env node
// tools/license-admin.js  —  licentiebeheer op je eigen Mac (niet op Vercel).
// Alles behalve 'keygen' leest de geheime sleutel uit de env-var LIC_SIGNING_KEY,
// bv. uit de macOS-sleutelhanger:
//   export LIC_SIGNING_KEY="$(security find-generic-password -s continuity-bridge -a LIC_SIGNING_KEY -w)"
//
//   node tools/license-admin.js keygen                     nieuw sleutelpaar (seed + publieke sleutel)
//   node tools/license-admin.js pubkey                     publieke sleutel bij LIC_SIGNING_KEY (voor _LIC_PUBKEY)
//   node tools/license-admin.js issue "Naam" [JJJJ-MM-DD]  handmatige serial (standaard 1 jaar geldig)
//   node tools/license-admin.js token SERIAL MACHINE_UUID  activatietoken zonder server (support / tests)
//   node tools/license-admin.js verify SERIAL              serial controleren (LEGACY_SERIALS uit env)

const crypto = require('crypto');
const {
  normalizeSerial, verifySerial, issueSerial, signingSeed,
  signActivationToken, signingPublicKeyHex,
} = require('../lib/security');

function needSeed() {
  const seed = signingSeed();
  if (!seed) {
    console.error('LIC_SIGNING_KEY ontbreekt of is geen base64 van 32 bytes.');
    process.exit(1);
  }
  return seed;
}

const [cmd, ...args] = process.argv.slice(2);

switch (cmd) {
  case 'keygen': {
    const seed = crypto.randomBytes(32);
    console.log(`LIC_SIGNING_KEY=${seed.toString('base64')}`);
    console.log(`_LIC_PUBKEY    =${signingPublicKeyHex(seed)}`);
    break;
  }
  case 'pubkey':
    console.log(signingPublicKeyHex(needSeed()));
    break;
  case 'issue': {
    const [name, date] = args;
    if (!name) { console.error('Gebruik: issue "Naam" [JJJJ-MM-DD]'); process.exit(1); }
    const expiry = date ? new Date(`${date}T00:00:00Z`) : undefined;
    if (expiry && isNaN(expiry)) { console.error('Ongeldige datum.'); process.exit(1); }
    console.log(issueSerial(name, needSeed(), expiry));
    break;
  }
  case 'token': {
    const [serial, mid] = args;
    const seed  = needSeed();
    const check = verifySerial(serial || '', seed);
    if (!check.ok || !mid) {
      console.error(`Geen token: ${check.reason || 'machine-UUID ontbreekt'}`);
      process.exit(1);
    }
    console.log(signActivationToken({
      v: 1, serial: normalizeSerial(serial), name: check.name,
      exp: check.expiry.toISOString().slice(0, 10), mid, iat: new Date().toISOString(),
    }, seed));
    break;
  }
  case 'verify': {
    const check = verifySerial(args[0] || '', needSeed());
    console.log(JSON.stringify({ ...check, expiry: check.expiry?.toISOString().slice(0, 10) }));
    process.exit(check.ok ? 0 : 1);
  }
  default:
    console.error('Commando\'s: keygen | pubkey | issue | token | verify  (zie kop van dit bestand)');
    process.exit(1);
}
