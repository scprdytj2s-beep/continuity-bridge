// tests/github.test.js  —  node --test tests/github.test.js
// GitHub-opslag: een token zonder toegang tot de privé repo mag niet stil 'lukken'.

const test   = require('node:test');
const assert = require('node:assert');
const crypto = require('crypto');
const {
  readJsonFile, writeJsonFile, issueSerial, signActivationToken, normalizeSerial,
} = require('../lib/security');

const REPO = 'eigenaar/prive';

// Nep-GitHub: routes = { 'GET /repos/eigenaar/prive': status, ... }; rest → 404.
// files = { 'data/x.json': [...] } — inhoud bij GET; PUT-bodies komen in calls.puts.
function fakeGithub(routes, files = {}) {
  const calls = [];
  calls.puts = {};
  global.fetch = async (url, opts = {}) => {
    const path = new URL(url).pathname;
    const key = `${opts.method || 'GET'} ${path}`;
    calls.push(key);
    if (url.includes('raw.githubusercontent.com')) return new Response('[]', { status: 200 });
    const file = path.split('/contents/')[1];
    if (opts.method === 'PUT' && routes[key] === 200) {
      calls.puts[file] = JSON.parse(Buffer.from(JSON.parse(opts.body).content, 'base64'));
    }
    const status = routes[key] || 404;
    const body = status === 200 && key.startsWith('GET') && file
      ? { content: Buffer.from(JSON.stringify(files[file] || [])).toString('base64'), sha: 'abc' } : {};
    return new Response(JSON.stringify(body), { status });
  };
  return calls;
}

function callApi(name, body) {
  const handler = require(`../api/${name}`);
  return new Promise((resolve) => {
    const res = {
      statusCode: 200,
      status(c) { this.statusCode = c; return this; },
      json(o)   { resolve({ status: this.statusCode, body: o }); },
      send(t)   { resolve({ status: this.statusCode, body: t }); },
    };
    handler({ method: 'POST', headers: {}, body }, res);
  });
}

test('bestand bestaat nog niet, repo wel bereikbaar → lege lijst', async () => {
  fakeGithub({ [`GET /repos/${REPO}`]: 200 });
  assert.deepEqual(await readJsonFile(REPO, 'data/x.json', 't'), { data: [], sha: null });
});

test('token zonder toegang tot de repo → duidelijke fout bij lezen', async () => {
  fakeGithub({});
  await assert.rejects(readJsonFile(REPO, 'data/x.json', 't'), /geen toegang tot eigenaar\/prive/);
});

test('schrijven met 404 → fout in plaats van stil slagen', async () => {
  fakeGithub({});
  await assert.rejects(writeJsonFile(REPO, 'data/x.json', 't', [], null, 'm'), /GitHub PUT 404/);
});

test('activate: geen toegang → toch token (fail open), maar met waarschuwing', async () => {
  const seed = crypto.randomBytes(32);
  process.env.LIC_SIGNING_KEY = seed.toString('base64');
  process.env.GITHUB_TOKEN    = 'zonder-toegang';
  process.env.LICENSES_REPO   = REPO;
  fakeGithub({});
  const handler = require('../api/activate');
  const body = await new Promise((resolve) => handler(
    { method: 'POST', headers: {}, body: { serial: issueSerial('Anna', seed), machine_uuid: 'M1' } },
    { status() { return this; }, json: resolve, send: resolve }));
  assert.equal(body.ok, true);
  assert.ok(body.token);
  assert.equal(body.warning, 'read_failed');
});

test('activate: werkende toegang → activatie wordt echt weggeschreven', async () => {
  const seed = crypto.randomBytes(32);
  process.env.LIC_SIGNING_KEY = seed.toString('base64');
  const calls = fakeGithub({
    [`GET /repos/${REPO}`]: 200,
    [`PUT /repos/${REPO}/contents/data/activations.json`]: 200,
  });
  const handler = require('../api/activate');
  const body = await new Promise((resolve) => handler(
    { method: 'POST', headers: {}, body: { serial: issueSerial('Bert', seed), machine_uuid: 'M2' } },
    { status() { return this; }, json: resolve, send: resolve }));
  assert.equal(body.ok, true);
  assert.equal(body.warning, undefined);
  assert.ok(calls.includes(`PUT /repos/${REPO}/contents/data/activations.json`));
});

// ── Deactiveren ("Verwijder licentie") ──────────────────────────────────────
function setupDeactivate() {
  const seed = crypto.randomBytes(32);
  process.env.LIC_SIGNING_KEY = seed.toString('base64');
  process.env.GITHUB_TOKEN    = 't';
  process.env.LICENSES_REPO   = REPO;
  const serial = normalizeSerial(issueSerial('Anna', seed));
  const token  = signActivationToken({ v: 1, serial, name: 'Anna', exp: '2099-01-01', mid: 'MAC-1' }, seed);
  const files  = { 'data/activations.json': [
    { serial, machine_uuid: 'MAC-1', activated_at: 'x' },
    { serial: 'CBANDERE', machine_uuid: 'MAC-9', activated_at: 'y' },
  ] };
  return { seed, serial, token, files };
}
const ACT = `/repos/${REPO}/contents/data/activations.json`;

test('deactivate: echt token → alleen die koppeling verdwijnt', async () => {
  const { token, files } = setupDeactivate();
  const calls = fakeGithub({ [`GET ${ACT}`]: 200, [`PUT ${ACT}`]: 200 }, files);
  const r = await callApi('deactivate', { token });
  assert.deepEqual(r.body, { ok: true });
  assert.deepEqual(calls.puts['data/activations.json'].map(a => a.machine_uuid), ['MAC-9']);
});

test('deactivate: daarna kan dezelfde serial op een andere machine', async () => {
  const { serial, token, files } = setupDeactivate();
  fakeGithub({ [`GET ${ACT}`]: 200, [`PUT ${ACT}`]: 200 }, files);
  // vóór het vrijgeven: andere machine geweigerd
  assert.equal((await callApi('activate', { serial, machine_uuid: 'MAC-2' })).body.reason, 'al_gebonden');
  await callApi('deactivate', { token });
  // nu zonder de oude koppeling
  fakeGithub({ [`GET ${ACT}`]: 200, [`PUT ${ACT}`]: 200 },
             { 'data/activations.json': files['data/activations.json'].slice(1) });
  const r = await callApi('activate', { serial, machine_uuid: 'MAC-2' });
  assert.equal(r.body.ok, true);
  assert.ok(r.body.token);
});

test('deactivate: vervalst of ander-sleutel-token → geweigerd, niets geschreven', async () => {
  const { serial, token, files } = setupDeactivate();
  const calls = fakeGithub({ [`GET ${ACT}`]: 200, [`PUT ${ACT}`]: 200 }, files);
  const other = signActivationToken({ v: 1, serial, mid: 'MAC-1' }, crypto.randomBytes(32));
  assert.deepEqual((await callApi('deactivate', { token: other })).body, { ok: false, reason: 'ongeldig' });
  const [p, b, sig] = token.split('.');
  const tampered = `${p}.${Buffer.from(JSON.stringify({ v: 1, serial, mid: 'MAC-9' })).toString('base64url')}.${sig}`;
  assert.equal((await callApi('deactivate', { token: tampered })).body.reason, 'ongeldig');
  assert.equal((await callApi('deactivate', { token: 'onzin' })).body.reason, 'ongeldig');
  assert.ok(!calls.some(c => c.startsWith('PUT')));
});

test('deactivate: GitHub-storing → 503 (app vraagt of je toch wilt verwijderen)', async () => {
  const { token } = setupDeactivate();
  fakeGithub({});
  const r = await callApi('deactivate', { token });
  assert.equal(r.status, 503);
});
