// api/feedback.js  —  Vercel serverless function
// GET  → recente open feedback-issues (publieke lijst op de feedbackpagina)
// POST → nieuwe melding: issue in de publieke repo, contactgegevens + bijlagen
//        privé in de licentie-repo, bevestigingsmail naar de melder.

const {
  escapeHtml, cleanLine, cleanText, isEmail,
  ghRequest, readJsonFile, writeJsonFile, privateRepo,
  rateLimited, clientIp,
} = require('../lib/security');

const OWNER  = 'scprdytj2s-beep';
const REPO   = 'continuity-bridge';
const TOKEN  = process.env.GITHUB_TOKEN;
const RESEND = process.env.RESEND_API_KEY;
const FROM   = 'support@studiomichielboesveldt.nl <info@studiomichielboesveldt.nl>';
const ADMIN  = 'info@studiomichielboesveldt.nl';
const ORIGIN = 'https://studiomichielboesveldt.nl';

const LABEL_MAP     = { Bug: 'bug', Verzoek: 'enhancement' };
const CONTACTS_PATH = 'data/feedback-contacts.json';
const MAX_UPLOAD    = 5 * 1024 * 1024;
const REQUEST_EXTS  = ['pdf', 'ale', 'bin', 'avb', 'txt'];

module.exports = async function handler(req, res) {
  res.setHeader('Access-Control-Allow-Origin', ORIGIN);

  if (req.method === 'GET') {
    try {
      const issues = await ghRequest('GET',
        `https://api.github.com/repos/${OWNER}/${REPO}/issues?state=open&labels=feedback&per_page=20`,
        TOKEN);
      // CDN-cache: anders kost elke paginaweergave een API-call met ons token
      res.setHeader('Cache-Control', 's-maxage=300, stale-while-revalidate=600');
      return res.status(200).json((issues || []).map(i => ({
        title:      i.title,
        created_at: i.created_at,
        url:        i.html_url,
        type:       labelType(i.labels),
        reporter:   firstName(bodyField(i.body, 'Naam')),
        version:    bodyField(i.body, 'Versie'),
      })));
    } catch (err) {
      console.error('Feedback list failed:', err.message);
      return res.status(200).json([]);
    }
  }

  if (req.method === 'POST') {
    if (rateLimited(`fb:${clientIp(req)}`, 5, 10 * 60 * 1000)) {
      return res.status(429).json({ error: 'too many requests' });
    }

    const b = req.body || {};
    const type        = LABEL_MAP[b.type] ? b.type : 'Bug';
    const name        = cleanLine(b.name, 80) || 'Anoniem';
    const email       = cleanLine(b.email, 254);
    const version     = cleanLine(b.version, 40);
    const platform    = cleanLine(b.platform, 60);
    const osVersion   = cleanLine(b.osVersion, 60);
    const description = cleanText(b.description, 5000);
    const steps       = cleanText(b.steps, 5000);

    if (!description || !isEmail(email)) {
      return res.status(400).json({ error: 'missing required fields' });
    }

    // Bijlagen alleen als ze echt zijn wat ze beweren te zijn, en privé opgeslagen
    // (screenshots kunnen productie-info bevatten; de issues-repo is publiek).
    const shot = decodeUpload(b.screenshotB64);
    if (b.screenshotB64 && (!shot || !isImage(shot))) {
      return res.status(400).json({ error: 'invalid screenshot' });
    }
    const reqExt  = String(b.requestFileName || '').split('.').pop().toLowerCase();
    const reqFile = decodeUpload(b.requestFileB64);
    if (b.requestFileB64 && (!reqFile || !REQUEST_EXTS.includes(reqExt) ||
        (reqExt === 'pdf' && reqFile.subarray(0, 5).toString('latin1') !== '%PDF-'))) {
      return res.status(400).json({ error: 'invalid file' });
    }

    const screenshotUrl  = shot    ? await uploadPrivate(shot,    b.screenshotName,  'screenshots') : null;
    const requestFileUrl = reqFile ? await uploadPrivate(reqFile, b.requestFileName, 'files')       : null;

    const label = LABEL_MAP[type];
    const short = cleanLine(description, 80);
    const title = `[${type}] ${short}${description.length > 80 ? '…' : ''}`;

    // Publieke issue: alleen voornaam, géén e-mailadres
    const bodyParts = [
      `**Naam:** ${firstName(name)}`,
      `**Versie:** ${version || 'onbekend'}`,
      `**Type:** ${type}`,
    ];
    if (platform)   bodyParts.push(`**Platform:** ${platform}`);
    if (osVersion)  bodyParts.push(`**OS versie:** ${osVersion}`);
    bodyParts.push('', '### Beschrijving', description);
    if (steps)          bodyParts.push('', '### Wat deed je op het moment dat het misging?', steps);
    if (screenshotUrl)  bodyParts.push('', '### Screenshot', `Privé opgeslagen: [bekijken](${screenshotUrl})`);
    if (requestFileUrl) bodyParts.push('', '### Bijgevoegd bestand', `Privé opgeslagen: [bekijken](${requestFileUrl})`);

    let issue;
    try {
      issue = await ghRequest('POST', `https://api.github.com/repos/${OWNER}/${REPO}/issues`, TOKEN,
        { title, body: bodyParts.join('\n'), labels: ['feedback', label] });
    } catch (err) {
      console.error('Issue create failed:', err.message);
      return res.status(500).json({ error: 'github error' });
    }

    // Contactgegevens privé bewaren voor de "opgelost"-mail (zie notify-resolved)
    try {
      const repo = privateRepo();
      const { data, sha } = await readJsonFile(repo, CONTACTS_PATH, TOKEN);
      data.push({ issue: issue.number, name, email, created_at: new Date().toISOString(), notified: false });
      await writeJsonFile(repo, CONTACTS_PATH, TOKEN, data, sha, `feedback contact #${issue.number}`);
    } catch (err) {
      console.error('Contact store failed:', err.message);
    }

    // Email naar indiener + bcc admin
    await sendEmail({ email, name, type, description, version, platform, issueUrl: issue.html_url });

    return res.status(201).json({ url: issue.html_url });
  }

  res.status(405).end();
};

function decodeUpload(b64) {
  if (typeof b64 !== 'string' || !b64) return null;
  const clean = b64.replace(/^data:[^,]*,/, '');
  if (clean.length > Math.ceil(MAX_UPLOAD * 4 / 3) + 4) return null;
  const buf = Buffer.from(clean, 'base64');
  return buf.length && buf.length <= MAX_UPLOAD ? buf : null;
}

function isImage(buf) {
  const hex = buf.subarray(0, 4).toString('hex');
  const ftyp = buf.subarray(4, 12).toString('latin1');
  return hex === '89504e47' ||                       // PNG
         hex.startsWith('ffd8ff') ||                  // JPEG
         hex === '47494638' ||                        // GIF
         (hex === '52494646' && buf.subarray(8, 12).toString('latin1') === 'WEBP') ||
         /^ftyp(heic|heix|mif1|msf1)$/.test(ftyp);    // HEIC (iPhone)
}

async function uploadPrivate(buf, filename, folder) {
  try {
    const ts   = Date.now();
    const safe = String(filename || 'bestand').replace(/[^a-zA-Z0-9._-]/g, '_').slice(0, 80);
    const path = `feedback-uploads/${folder}/${ts}-${safe}`;
    const data = await ghRequest('PUT',
      `https://api.github.com/repos/${privateRepo()}/contents/${path}`, TOKEN,
      { message: `feedback upload ${ts}`, content: buf.toString('base64') });
    return data?.content?.html_url || null;
  } catch (err) {
    console.error('Upload failed:', err.message);
    return null;
  }
}

async function sendEmail({ email, name, type, description, version, platform, issueUrl }) {
  if (!RESEND) return;
  const voornaam  = escapeHtml(name !== 'Anoniem' ? firstName(name) : 'daar');
  const typeLabel = type === 'Bug' ? 'bugmelding' : 'verzoek';
  const typeEmoji = type === 'Bug' ? '🐛' : '💡';
  const platformInfo = platform
    ? `<p style="margin:0 0 8px"><strong>Platform:</strong> ${escapeHtml(platform)}</p>` : '';
  await fetch('https://api.resend.com/emails', {
    method: 'POST',
    headers: {
      Authorization: `Bearer ${RESEND}`,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      from: FROM,
      to:   email,
      bcc:  ADMIN,
      subject: `${typeEmoji} Ontvangen: jouw ${typeLabel} voor Continuity Bridge`,
      html: `
        <div style="font-family:sans-serif;max-width:520px;margin:0 auto;color:#1a1a1a">
          <div style="background:#0C0618;padding:24px 32px;border-radius:12px 12px 0 0">
            <span style="color:#EDE8FF;font-weight:700;font-size:16px">Continuity Bridge</span>
          </div>
          <div style="border:1px solid #e5e5e5;border-top:none;padding:32px;border-radius:0 0 12px 12px">
            <p style="margin:0 0 16px">Hoi ${voornaam},</p>
            <p style="margin:0 0 16px">Je ${typeLabel} is goed ontvangen. Michiel pakt dit op bij de eerstvolgende versie.</p>
            <div style="background:#f9f9f9;border-radius:8px;padding:16px;margin:20px 0;font-size:13px;color:#444;border-left:4px solid #9B40FF">
              <p style="margin:0 0 8px"><strong>Versie:</strong> ${escapeHtml(version || 'onbekend')}</p>
              ${platformInfo}
              <p style="margin:0"><strong>Jouw melding:</strong></p>
              <div style="white-space:pre-wrap;margin-top:8px">${escapeHtml(description)}</div>
            </div>
            <p style="margin:0 0 8px;font-size:14px;color:#666">Bedankt voor je feedback!</p>
            <p style="margin:0;font-size:14px;color:#666">— Michiel</p>
            <p style="margin-top:16px;font-size:12px;color:#999">
              <a href="${escapeHtml(issueUrl)}" style="color:#9B40FF;text-decoration:none">Bekijk op GitHub</a>
            </p>
          </div>
        </div>
      `,
    }),
  });
}

function firstName(name) {
  return String(name || '').trim().split(/\s+/)[0] || '';
}

function labelType(labels) {
  const names = (labels || []).map(l => l.name);
  if (names.includes('enhancement')) return 'Verzoek';
  return 'Bug';
}

function bodyField(body, field) {
  const m = (body || '').match(new RegExp(`\\*\\*${field}:\\*\\*\\s*(.+)`));
  return m ? m[1].trim() : '';
}
