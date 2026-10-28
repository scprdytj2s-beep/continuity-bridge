// api/notify-resolved.js  —  Vercel serverless function
// POST { issue: <nummer> } → "je melding is opgelost"-mail naar de melder.
// Aangeroepen door .github/workflows/notify-resolved.yml zodra een
// feedback-issue als 'completed' wordt gesloten. Het e-mailadres staat privé
// (data/feedback-contacts.json), niet meer in de publieke issue. Geen geheim
// nodig: de functie controleert zelf bij GitHub of de issue echt opgelost is,
// en mailt elke melder hooguit één keer.

const {
  escapeHtml, ghRequest, readJsonFile, writeJsonFile, privateRepo,
} = require('../lib/security');

const OWNER = 'scprdytj2s-beep';
const REPO  = 'continuity-bridge';
const CONTACTS_PATH = 'data/feedback-contacts.json';

module.exports = async (req, res) => {
  if (req.method !== 'POST') return res.status(405).send('Method Not Allowed');

  const token  = process.env.GITHUB_TOKEN;
  const resend = process.env.RESEND_API_KEY;
  if (!token || !resend) return res.status(500).json({ error: 'not configured' });

  const num = Number((req.body || {}).issue);
  if (!Number.isInteger(num) || num <= 0) return res.status(400).json({ error: 'bad issue' });

  let issue;
  try {
    issue = await ghRequest('GET', `https://api.github.com/repos/${OWNER}/${REPO}/issues/${num}`, token);
  } catch (err) {
    console.error('Issue fetch failed:', err.message);
    return res.status(502).json({ error: 'github error' });
  }
  const labels = (issue?.labels || []).map(l => l.name);
  if (!issue || issue.state !== 'closed' || issue.state_reason !== 'completed' ||
      !labels.includes('feedback')) {
    return res.status(200).json({ sent: false, reason: 'not resolved feedback' });
  }

  const repo = privateRepo();
  let contacts, sha;
  try {
    ({ data: contacts, sha } = await readJsonFile(repo, CONTACTS_PATH, token));
  } catch (err) {
    console.error('Contacts read failed:', err.message);
    return res.status(502).json({ error: 'contacts unavailable' });
  }
  const contact = contacts.find(c => c.issue === num);
  if (!contact) return res.status(200).json({ sent: false, reason: 'no contact' });
  if (contact.notified) return res.status(200).json({ sent: false, reason: 'already notified' });

  // Eerst markeren, dan mailen: liever één gemiste mail dan herhaalde mails
  contact.notified = true;
  contact.notified_at = new Date().toISOString();
  try {
    await writeJsonFile(repo, CONTACTS_PATH, token, contacts, sha, `notified #${num}`);
  } catch (err) {
    console.error('Contacts write failed:', err.message);
    return res.status(502).json({ error: 'contacts write failed' });
  }

  let version = '';
  try {
    const rel = await ghRequest('GET', `https://api.github.com/repos/${OWNER}/${REPO}/releases/latest`, token);
    version = (rel?.tag_name || '').replace(/^v/, '');
  } catch { /* geen release — laat versie leeg */ }

  const isBug     = labels.includes('bug');
  const typeLabel = isBug ? 'bugmelding' : 'verzoek';
  const typeEmoji = isBug ? '🐛' : '💡';
  const name      = String(contact.name || '');
  const voornaam  = escapeHtml(name && name !== 'Anoniem' ? name.split(' ')[0] : 'daar');
  const body      = issue.body || '';
  const descMatch = body.match(/### Beschrijving\s*\n([\s\S]*?)(\n### |$)/);
  const desc      = escapeHtml((descMatch ? descMatch[1] : issue.title || '').trim());

  const versieRegel = version
    ? `<p style="margin:0 0 16px">De fix zit in de nieuwste versie (<strong>v${escapeHtml(version)}</strong>). Download 'm via de gebruikelijke link en test gerust of het nu goed gaat.</p>`
    : `<p style="margin:0 0 16px">De fix zit in de nieuwste versie. Download 'm via de gebruikelijke link en test gerust of het nu goed gaat.</p>`;

  const html = `
    <div style="font-family:sans-serif;max-width:520px;margin:0 auto;color:#1a1a1a">
      <div style="background:#0C0618;padding:24px 32px;border-radius:12px 12px 0 0">
        <span style="color:#EDE8FF;font-weight:700;font-size:16px">Continuity Bridge</span>
      </div>
      <div style="border:1px solid #e5e5e5;border-top:none;padding:32px;border-radius:0 0 12px 12px">
        <p style="margin:0 0 16px">Hoi ${voornaam},</p>
        <p style="margin:0 0 16px">Jouw ${typeLabel} voor Continuity Bridge is als het goed is nu opgelost. ${typeEmoji}</p>
        ${versieRegel}
        <div style="background:#f9f9f9;border-radius:8px;padding:16px;margin:20px 0;font-size:13px;color:#444;border-left:4px solid #9B40FF">
          <p style="margin:0"><strong>Jouw melding:</strong></p>
          <div style="white-space:pre-wrap;margin-top:8px">${desc}</div>
        </div>
        <p style="margin:0 0 20px">
          <a href="https://studiomichielboesveldt.nl/cbapp/"
             style="display:inline-block;background:#9B40FF;color:#fff;text-decoration:none;padding:10px 20px;border-radius:8px;font-weight:600;font-size:14px">
            Download de nieuwste versie
          </a>
        </p>
        <p style="margin:0;font-size:14px;color:#666">Bedankt voor je feedback!</p>
        <p style="margin:0;font-size:14px;color:#666">— Michiel</p>
      </div>
    </div>`;

  const resp = await fetch('https://api.resend.com/emails', {
    method: 'POST',
    headers: { Authorization: `Bearer ${resend}`, 'Content-Type': 'application/json' },
    body: JSON.stringify({
      from: 'support@studiomichielboesveldt.nl <info@studiomichielboesveldt.nl>',
      to:   contact.email,
      bcc:  'info@studiomichielboesveldt.nl',
      subject: `✅ Opgelost: jouw ${typeLabel} voor Continuity Bridge`,
      html,
    }),
  });
  if (!resp.ok) {
    console.error('Resend error:', resp.status, await resp.text());
    return res.status(502).json({ sent: false, error: 'mail failed' });
  }
  return res.status(200).json({ sent: true });
};
