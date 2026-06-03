const OWNER  = 'scprdytj2s-beep';
const REPO   = 'continuity-bridge';
const TOKEN  = process.env.GITHUB_TOKEN;
const RESEND = process.env.RESEND_API_KEY;
const FROM   = 'Continuity Bridge <noreply@studiomichielboesveldt.nl>';

const LABEL_MAP = { Bug: 'bug', Verzoek: 'enhancement' };

export default async function handler(req, res) {
  res.setHeader('Access-Control-Allow-Origin', '*');

  if (req.method === 'GET') {
    const r = await fetch(
      `https://api.github.com/repos/${OWNER}/${REPO}/issues?state=open&labels=feedback&per_page=20`,
      { headers: { Authorization: `token ${TOKEN}`, Accept: 'application/vnd.github+json' } }
    );
    const issues = await r.json();
    return res.status(200).json(issues.map(i => ({
      title:      i.title,
      created_at: i.created_at,
      url:        i.html_url,
      type:       labelType(i.labels),
      reporter:   bodyField(i.body, 'Naam'),
      version:    bodyField(i.body, 'Versie'),
    })));
  }

  if (req.method === 'POST') {
    const {
      type, name, email, version, platform, osVersion,
      description, steps,
      screenshotB64, screenshotName,
      requestFileB64, requestFileName,
    } = req.body;

    if (!description || !email) return res.status(400).json({ error: 'missing required fields' });

    // Upload screenshot / request file to repo
    const screenshotUrl   = await uploadFile(screenshotB64,   screenshotName,   'feedback-screenshots');
    const requestFileUrl  = await uploadFile(requestFileB64,  requestFileName,  'feedback-files');

    const label = LABEL_MAP[type] || 'bug';
    const title = `[${type}] ${description.slice(0, 80)}${description.length > 80 ? '…' : ''}`;

    const bodyParts = [
      `**Naam:** ${name || 'Anoniem'}`,
      `**E-mail:** ${email}`,
      `**Versie:** ${version || 'onbekend'}`,
      `**Type:** ${type}`,
    ];
    if (platform)   bodyParts.push(`**Platform:** ${platform}`);
    if (osVersion)  bodyParts.push(`**OS versie:** ${osVersion}`);
    bodyParts.push('', '### Beschrijving', description);
    if (steps)          bodyParts.push('', '### Wat deed je op het moment dat het misging?', steps);
    if (screenshotUrl)  bodyParts.push('', '### Screenshot', `![screenshot](${screenshotUrl})`);
    if (requestFileUrl) bodyParts.push('', '### Bijgevoegd bestand', `[${requestFileName}](${requestFileUrl})`);

    const r = await fetch(
      `https://api.github.com/repos/${OWNER}/${REPO}/issues`,
      {
        method: 'POST',
        headers: {
          Authorization: `token ${TOKEN}`,
          Accept: 'application/vnd.github+json',
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ title, body: bodyParts.join('\n'), labels: ['feedback', label] }),
      }
    );

    if (!r.ok) return res.status(500).json({ error: 'github error' });
    const issue = await r.json();

    // Bevestigingsmail
    await sendConfirmation({ email, name, type, description, issueUrl: issue.html_url });

    return res.status(201).json({ url: issue.html_url });
  }

  res.status(405).end();
}

async function uploadFile(b64, filename, folder) {
  if (!b64 || !filename) return null;
  const ts   = Date.now();
  const ext  = filename.split('.').pop() || 'bin';
  const path = `${folder}/${ts}-${filename.replace(/[^a-zA-Z0-9._-]/g, '_')}`;
  const r    = await fetch(
    `https://api.github.com/repos/${OWNER}/${REPO}/contents/${path}`,
    {
      method: 'PUT',
      headers: {
        Authorization: `token ${TOKEN}`,
        Accept: 'application/vnd.github+json',
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ message: `feedback upload ${ts}`, content: b64 }),
    }
  );
  if (!r.ok) return null;
  const data = await r.json();
  return data.content?.download_url || null;
}

async function sendConfirmation({ email, name, type, description, issueUrl }) {
  if (!RESEND) return;
  const voornaam = name && name !== 'Anoniem' ? name.split(' ')[0] : 'daar';
  const typeLabel = type === 'Bug' ? 'bugmelding' : 'verzoek';
  await fetch('https://api.resend.com/emails', {
    method: 'POST',
    headers: {
      Authorization: `Bearer ${RESEND}`,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      from: FROM,
      to:   email,
      subject: `Ontvangen: jouw ${typeLabel} voor Continuity Bridge`,
      html: `
        <div style="font-family:sans-serif;max-width:520px;margin:0 auto;color:#1a1a1a">
          <div style="background:#0C0618;padding:24px 32px;border-radius:12px 12px 0 0">
            <span style="color:#EDE8FF;font-weight:700;font-size:16px">Continuity Bridge</span>
          </div>
          <div style="border:1px solid #e5e5e5;border-top:none;padding:32px;border-radius:0 0 12px 12px">
            <p style="margin:0 0 16px">Hoi ${voornaam},</p>
            <p style="margin:0 0 16px">Je ${typeLabel} is goed ontvangen. Michiel pakt dit op bij de eerstvolgende versie.</p>
            <div style="background:#f5f5f5;border-radius:8px;padding:16px;margin:20px 0;font-size:14px;color:#444">
              <strong>Jouw melding:</strong><br/><br/>
              ${description.replace(/\n/g, '<br/>')}
            </div>
            <p style="margin:0 0 8px;font-size:14px;color:#666">Bedankt voor je feedback!</p>
            <p style="margin:0;font-size:14px;color:#666">— Michiel</p>
          </div>
        </div>
      `,
    }),
  });
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
