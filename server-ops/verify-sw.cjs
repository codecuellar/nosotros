// Local isolated SW contract check. Does not start servers or touch app data.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const handlers = {};
const stored = new Map();
const writes = [];
const deleted = [];
let response = new Response('shell', {status: 200});
let offline = false;
const cache = {
  async put(key, value) { writes.push(key); stored.set(key, value); },
  async match(key) { return stored.get(key)?.clone(); }
};
const sandbox = {
  URL, Request, Response, Set,
  fetch: async () => { if (offline) throw new Error('offline'); return response.clone(); },
  caches: {open: async () => cache, keys: async () => ['nosotros-shell-old', 'unrelated'], delete: async key => deleted.push(key)},
  self: {location: {origin: 'https://example.test'}, skipWaiting: async () => {}, clients: {claim: async () => {}}, addEventListener: (type, fn) => { handlers[type] = fn; }}
};
// Resolve root-relative requests the same way a browser worker does.
sandbox.Request = class extends Request { constructor(url, init) { super(new URL(url, sandbox.self.location.origin), init); } };
vm.runInNewContext(fs.readFileSync(path.join(__dirname, '..', 'sw.js'), 'utf8'), sandbox);
async function lifecycle(name) { let promise; handlers[name]({waitUntil: p => { promise = p; }}); await promise; }
async function request(route, mode = 'cors', method = 'GET') {
  let promise;
  handlers.fetch({request: {url: new URL(route, 'https://example.test').href, method, mode}, respondWith: p => { promise = p; }});
  return promise ? await promise : null;
}
(async () => {
  await lifecycle('install');
  assert.deepEqual(writes, ['/', '/index.html', '/sync.js', '/manifest.json', '/icon-192.png', '/icon-512.png']);
  await lifecycle('activate');
  assert.deepEqual(deleted, ['nosotros-shell-old']);
  for (const route of ['/api', '/api/session', '/api/health', '/uploads/a.png', '/secret', '/?x=1', 'https://other.test/']) {
    assert.equal(await request(route, 'navigate'), null, route);
  }
  assert.equal(await request('/', 'cors', 'POST'), null);
  const before = writes.length;
  response = new Response('unauthorized', {status: 401});
  assert.equal((await request('/', 'navigate')).status, 401);
  assert.equal(writes.length, before);
  response = new Response('failure', {status: 503});
  assert.equal((await request('/', 'navigate')).status, 503);
  assert.equal(writes.length, before);
  offline = true;
  assert.equal(await (await request('/', 'navigate')).text(), 'shell');
  assert.equal(await (await request('/sync.js')).text(), 'shell');
  assert.equal(await request('/api/session', 'navigate'), null);
  console.log('PASS SW: exact 6-entry shell, scoped cleanup, 8 bypasses, 401/503 uncached, offline navigation/assets, API never fallback.');
})().catch(error => { console.error(error); process.exitCode = 1; });
