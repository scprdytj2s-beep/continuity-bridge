// api/deactivate.js  —  Vercel serverless function
// POST { token } → koppeling van een licentie aan een machine opheffen
// ("Verwijder licentie" in de app), zodat hij op een andere computer
// geactiveerd kan worden. Het getekende activatietoken bewijst dat de aanvrager
// die machine is; zonder token kan niemand andermans koppeling losmaken.
//   { ok: true }              → vrijgegeven (of er stond niets vastgelegd)
//   { ok: false, reason }     → ongeldig token
//   HTTP 5xx                  → storing (app vraagt of je toch wilt verwijderen)

const {
  verifyActivationToken, signingSeed, readJsonFile, writeJsonFile, privateRepo,
  rateLimited, clientIp,
} = require('../lib/security');

module.exports = async (req, res) => {
  if (req.method !== 'POST') return res.status(405).send('Method Not Allowed');

  if (rateLimited(`deact:${clientIp(req)}`, 20, 10 * 60 * 1000)) {
    return res.status(429).json({ ok: false, reason: 'te_veel_pogingen' });
  }

  let body = req.body || {};
  if (typeof body === 'string') {
    try { body = JSON.parse(body); } catch { body = {}; }
  }

  const seed = signingSeed();
  if (!seed) {
    console.error('LIC_SIGNING_KEY ontbreekt of is ongeldig');
    return res.status(503).json({ ok: false, reason: 'server_config' });
  }

  const claims = verifyActivationToken(body.token, seed);
  if (!claims) return res.status(200).json({ ok: false, reason: 'ongeldig' });

  const token = process.env.GITHUB_TOKEN;
  if (!token) {
    // Zonder token is er ook nooit een koppeling vastgelegd
    console.warn('GITHUB_TOKEN not set, nothing to release');
    return res.status(200).json({ ok: true, warning: 'no_token' });
  }

  const repo = privateRepo();
  const path = 'data/activations.json';
  try {
    const { data, sha } = await readJsonFile(repo, path, token);
    const rest = data.filter(a => !(a.serial === claims.serial && a.machine_uuid === claims.mid));
    if (rest.length !== data.length) {
      await writeJsonFile(repo, path, token, rest, sha,
                          `deactivate: ${String(claims.serial).slice(0, 7)}…`);
    }
  } catch (err) {
    console.error('Deactivate failed:', err.message);
    return res.status(503).json({ ok: false, reason: 'storing' });
  }

  return res.status(200).json({ ok: true });
};
