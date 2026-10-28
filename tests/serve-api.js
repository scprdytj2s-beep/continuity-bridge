// tests/serve-api.js  —  draait api/activate.js en api/deactivate.js lokaal
// (alleen voor tests) onder /api/…. Print de poort op stdout; env
// (LIC_SIGNING_KEY, LEGACY_SERIALS, ...) zoals op Vercel.

const http = require('http');
const handlers = {
  '/api/activate':   require('../api/activate'),
  '/api/deactivate': require('../api/deactivate'),
};

http.createServer((req, res) => {
  let raw = '';
  req.on('data', c => { raw += c; });
  req.on('end', () => {
    // Vercel-achtige req/res
    req.body = raw;
    res.status = (code) => { res.statusCode = code; return res; };
    res.json   = (obj)  => { res.setHeader('Content-Type', 'application/json'); res.end(JSON.stringify(obj)); };
    res.send   = (txt)  => res.end(String(txt));
    const handler = handlers[new URL(req.url, 'http://x').pathname];
    if (!handler) { res.statusCode = 404; return res.end('Not Found'); }
    handler(req, res).catch(err => { res.statusCode = 500; res.end(String(err)); });
  });
}).listen(0, '127.0.0.1', function () {
  console.log(this.address().port);
});
