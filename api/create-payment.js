// api/create-payment.js  —  Vercel serverless function
// POST { name, email } → { checkoutUrl }

const { createMollieClient } = require('@mollie/api-client');
const { cleanLine, isEmail, rateLimited, clientIp } = require('../lib/security');

const SITE = 'https://studiomichielboesveldt.nl';

module.exports = async (req, res) => {
  if (req.method !== 'POST') {
    return res.status(405).json({ error: 'Method Not Allowed' });
  }

  if (rateLimited(`pay:${clientIp(req)}`, 10, 10 * 60 * 1000)) {
    return res.status(429).json({ error: 'Te veel pogingen. Probeer het later opnieuw.' });
  }

  const body  = req.body || {};
  const name  = cleanLine(body.name, 80);
  const email = cleanLine(body.email, 254);

  if (!name || !isEmail(email)) {
    return res.status(400).json({ error: 'Naam en e-mailadres zijn verplicht.' });
  }

  const mollie = createMollieClient({ apiKey: process.env.MOLLIE_API_KEY });

  try {
    const payment = await mollie.payments.create({
      amount:      { currency: 'EUR', value: '4.99' }, // moet exact 2 decimalen zijn
      description: 'Continuity Bridge – Jaarlicentie',
      redirectUrl: `${SITE}/cbapp/success.html?name=${encodeURIComponent(name)}`,
      webhookUrl:  `${SITE}/api/mollie-webhook`,
      metadata:    { name, email },
    });

    // getCheckoutUrl() werkt niet meer in Mollie client v3+ — gebruik _links
    const checkoutUrl = payment._links?.checkout?.href ?? payment.getCheckoutUrl?.();
    if (!checkoutUrl) throw new Error('Geen checkout URL ontvangen van Mollie.');
    return res.status(200).json({ checkoutUrl });
  } catch (err) {
    console.error('Mollie error:', err);
    return res.status(502).json({
      error: 'Betaling kon niet worden aangemaakt. Probeer het later opnieuw.',
    });
  }
};
