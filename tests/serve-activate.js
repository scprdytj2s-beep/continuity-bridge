// tests/serve-activate.js  —  draait api/activate.js lokaal (alleen voor tests).
// Print de poort op stdout; env (LIC_SIGNING_KEY, LEGACY_SERIALS, ...) zoals op Vercel.

const http = require('http');
const handler = require('../api/activate');

http.createServer((req, res) => {
  let raw = '';
  req.on('data', c => { raw += c; });
  req.on('end', () => {
    // Vercel-achtige req/res
    req.body = raw;
    res.status = (code) => { res.statusCode = code; return res; };
    res.json   = (obj)  => { res.setHeader('Content-Type', 'application/json'); res.end(JSON.stringify(obj)); };
    res.send   = (txt)  => res.end(String(txt));
    handler(req, res).catch(err => { res.statusCode = 500; res.end(String(err)); });
  });
}).listen(0, '127.0.0.1', function () {
  console.log(this.address().port);
});
