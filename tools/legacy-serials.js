#!/usr/bin/env node
// tools/legacy-serials.js  —  stelt de waarde voor LEGACY_SERIALS (Vercel-env) samen:
// alle serials van vóór v1.5 die moeten blijven werken. Elke serial wordt
// gecontroleerd met de oude sleutel; ongeldige vallen af.
//
//   node tools/legacy-serials.js [--github] [--mollie] [bestand…] [serial…]
//
//   --github   data/licenses.json uit de privé repo (GITHUB_TOKEN, of via `gh auth token`)
//   --mollie   betaalde Mollie-betalingen met naam in metadata: serial wordt
//              gereconstrueerd (vervaldag = betaaldag + 365, en +1 voor de zekerheid)
//              (MOLLIE_API_KEY; alleen lezen)
//   bestand    elk tekstbestand (bv. geëxporteerde mails, .mbox): alle CB-serials eruit
//   serial     losse serials, bv. handmatig uitgegeven
//
// stdout: de waarde voor LEGACY_SERIALS. stderr: overzicht om na te lopen.

const fs = require('fs');
const { execSync } = require('child_process');
const {
  serialCore, privateRepo, readJsonFile, cleanLine,
  LEGACY_HMAC_KEY, LIC_EPOCH_MS, serialMac, base32encode, base32decode,
} = require('../lib/security');

const SERIAL_RE = /CB(?:-?[A-Z2-7]{4}){6}/gi;
const found = new Map();   // core → { name, expiry, sources:Set }

function legacyDecode(serial) {
  const core = serialCore(serial);
  const raw  = core.length === 24 && base32decode(core);
  if (!raw || raw.length !== 15) return null;
  if (!serialMac(LEGACY_HMAC_KEY, raw.subarray(0, 10)).equals(raw.subarray(10))) return null;
  return {
    core,
    name:   raw.subarray(2, 10).toString('utf8').replace(/\0+$/, ''),
    expiry: new Date(LIC_EPOCH_MS + raw.readUInt16BE(0) * 86400000).toISOString().slice(0, 10),
  };
}

function add(serial, source) {
  const d = legacyDecode(serial);
  if (!d) { console.error(`  overgeslagen (geen geldige oude serial): ${serial}  [${source}]`); return; }
  const entry = found.get(d.core) || { ...d, sources: new Set() };
  entry.sources.add(source);
  found.set(d.core, entry);
}

// Zoals de oude generateSerial in api/mollie-webhook.js
function legacySerial(name, expiryDays) {
  const payload = Buffer.alloc(10);
  payload.writeUInt16BE(expiryDays & 0xffff);
  Buffer.from(name.trim(), 'utf8').subarray(0, 8).copy(payload, 2);
  return `CB${base32encode(Buffer.concat([payload, serialMac(LEGACY_HMAC_KEY, payload)]))}`;
}

async function fromGithub() {
  const token = process.env.GITHUB_TOKEN || execSync('gh auth token').toString().trim();
  const { data } = await readJsonFile(privateRepo(), 'data/licenses.json', token);
  for (const e of data) add(e.serial || '', 'cb-licenses');
}

async function fromMollie() {
  const key = process.env.MOLLIE_API_KEY;
  if (!/^(live|test)_\w+$/.test(key || '')) {
    throw new Error('MOLLIE_API_KEY ontbreekt of is geen echte sleutel (begint met live_)');
  }
  let url = 'https://api.mollie.com/v2/payments?limit=250';
  while (url) {
    const r = await fetch(url, { headers: { Authorization: `Bearer ${key}` } });
    if (!r.ok) throw new Error(`Mollie ${r.status}: ${(await r.text()).slice(0, 200)}`);
    const page = await r.json();
    for (const p of page._embedded?.payments || []) {
      if (p.status !== 'paid') continue;
      const name = cleanLine(p.metadata?.name, 80);
      if (!name) {
        // Betaallink zonder naam → serial is (als het goed is) handmatig uitgegeven
        console.error(`  zonder naam (handmatig?): ${p.paidAt?.slice(0, 10)} ${p.amount.value} ` +
                      `${p.details?.consumerName || ''} — ${p.description}`);
        continue;
      }
      const day = Math.floor((Date.parse(p.paidAt || p.createdAt) - LIC_EPOCH_MS) / 86400000) + 365;
      add(legacySerial(name, day), `mollie ${p.id}`);
      add(legacySerial(name, day + 1), `mollie ${p.id} (+1 dag)`);
    }
    url = page._links?.next?.href;
  }
}

(async () => {
  const args = process.argv.slice(2);
  // Eén bron die faalt, stopt de rest niet
  const tryStep = async (label, fn) => {
    try { await fn(); } catch (err) { console.error(`  ✗ ${label} overgeslagen: ${err.message}`); }
  };
  if (args.includes('--github')) await tryStep('cb-licenses', fromGithub);
  if (args.includes('--mollie')) await tryStep('Mollie', fromMollie);
  for (const a of args.filter(a => !a.startsWith('--'))) {
    if (fs.existsSync(a)) {
      for (const m of fs.readFileSync(a, 'utf8').match(SERIAL_RE) || []) add(m, a);
    } else if (/[\/.]/.test(a)) {
      console.error(`  ✗ bestand niet gevonden: ${a}`);
    } else {
      add(a, 'handmatig');
    }
  }

  console.error(`\n${found.size} serial(s):`);
  for (const e of [...found.values()].sort((a, b) => a.expiry.localeCompare(b.expiry))) {
    console.error(`  CB${e.core}  ${e.name.padEnd(8)}  t/m ${e.expiry}  [${[...e.sources].join(', ')}]`);
  }
  console.log([...found.keys()].map(c => `CB${c}`).join(','));
})().catch(err => { console.error(err.message); process.exit(1); });
