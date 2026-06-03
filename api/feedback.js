const OWNER = 'scprdytj2s-beep';
const REPO  = 'continuity-bridge';
const TOKEN = process.env.GITHUB_TOKEN;

const LABEL_MAP = {
  Bug:     'bug',
  Verzoek: 'enhancement',
};

export default async function handler(req, res) {
  res.setHeader('Access-Control-Allow-Origin', '*');

  // GET — return recent open issues
  if (req.method === 'GET') {
    const r = await fetch(
      `https://api.github.com/repos/${OWNER}/${REPO}/issues?state=open&labels=feedback&per_page=20`,
      { headers: { Authorization: `token ${TOKEN}`, Accept: 'application/vnd.github+json' } }
    );
    const issues = await r.json();
    const out = issues.map(i => ({
      title:      i.title,
      created_at: i.created_at,
      url:        i.html_url,
      type:       labelType(i.labels),
      reporter:   bodyField(i.body, 'Naam'),
      version:    bodyField(i.body, 'Versie'),
    }));
    return res.status(200).json(out);
  }

  // POST — create issue
  if (req.method === 'POST') {
    const { type, name, version, platform, osVersion, description, steps, screenshotB64, screenshotName } = req.body;
    if (!description) return res.status(400).json({ error: 'description required' });

    // Upload screenshot to repo if provided
    let screenshotUrl = null;
    if (screenshotB64 && screenshotName) {
      const ts   = Date.now();
      const ext  = screenshotName.split('.').pop() || 'png';
      const path = `feedback-screenshots/${ts}.${ext}`;
      const up   = await fetch(
        `https://api.github.com/repos/${OWNER}/${REPO}/contents/${path}`,
        {
          method: 'PUT',
          headers: {
            Authorization: `token ${TOKEN}`,
            Accept: 'application/vnd.github+json',
            'Content-Type': 'application/json',
          },
          body: JSON.stringify({
            message: `feedback screenshot ${ts}`,
            content: screenshotB64,
          }),
        }
      );
      if (up.ok) {
        const upData = await up.json();
        screenshotUrl = upData.content?.download_url;
      }
    }

    const label = LABEL_MAP[type] || 'bug';
    const title = `[${type}] ${description.slice(0, 80)}${description.length > 80 ? '…' : ''}`;
    const body  = [
      `**Naam:** ${name || 'Anoniem'}`,
      `**Versie:** ${version || 'onbekend'}`,
      `**Platform:** ${platform || 'onbekend'}`,
      osVersion ? `**OS versie:** ${osVersion}` : '',
      `**Type:** ${type}`,
      '',
      '### Beschrijving',
      description,
      steps ? `\n### Wat deed je op het moment dat het misging?\n${steps}` : '',
      screenshotUrl ? `\n### Screenshot\n![screenshot](${screenshotUrl})` : '',
    ].filter(Boolean).join('\n');

    const r = await fetch(
      `https://api.github.com/repos/${OWNER}/${REPO}/issues`,
      {
        method: 'POST',
        headers: {
          Authorization: `token ${TOKEN}`,
          Accept: 'application/vnd.github+json',
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ title, body, labels: ['feedback', label] }),
      }
    );

    if (!r.ok) return res.status(500).json({ error: 'github error' });
    const issue = await r.json();
    return res.status(201).json({ url: issue.html_url });
  }

  res.status(405).end();
}

function labelType(labels) {
  const names = labels.map(l => l.name);
  if (names.includes('enhancement')) return 'Verzoek';
  return 'Bug';
}

function bodyField(body, field) {
  const m = (body || '').match(new RegExp(`\\*\\*${field}:\\*\\*\\s*(.+)`));
  return m ? m[1].trim() : '';
}
