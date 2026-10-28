// tests/github.test.js  —  node --test tests/github.test.js
// GitHub-opslag: een token zonder toegang tot de privé repo mag niet stil 'lukken'.

const test   = require('node:test');
const assert = require('node:assert');
const crypto = require('crypto');
const { readJsonFile, writeJsonFile, issueSerial } = require('../lib/security');

const REPO = 'eigenaar/prive';

// Nep-GitHub: routes = { 'GET /repos/eigenaar/prive': status, ... }; rest → 404
function fakeGithub(routes) {
  const calls = [];
  global.fetch = async (url, opts = {}) => {
    const key = `${opts.method || 'GET'} ${new URL(url).pathname}`;
    calls.push(key);
    if (url.includes('raw.githubusercontent.com')) return new Response('[]', { status: 200 });
    const status = routes[key] || 404;
    const body = status === 200 && key.includes('/contents/')
      ? { content: Buffer.from('[]').toString('base64'), sha: 'abc' } : {};
    return new Response(JSON.stringify(body), { status });
  };
  return calls;
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
