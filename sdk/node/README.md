# Fast-KV Node.js SDK (Phase 8)

Local dependency (not published to npm):

```bash
npm install ./sdk/node
```

```js
const {FastKV} = require('fastkv-client');

(async () => {
  const db = new FastKV({host: '127.0.0.1', port: 7001});
  await db.set('username', 'awnish');
  console.log(await db.get('username'));
  await db.set('session:101', 'active', {ttl: 60});
  console.log(await db.ttl('session:101'));
})();
```

No third-party dependencies. Node 18+. `timeout` uses milliseconds.
Keys and values must be whitespace-free single tokens. `get()` maps `(nil)`
to null; literal `(nil)` is ambiguous. `set(key, value, {ttl})` sends one
router `SET ... EX` with manager-restart intent recovery (not strict power-loss
atomicity). `{persist: true}` forces a permanent key, `{keepTTL: true}` retains
its deadline, and plain `set()` inherits the developer database default set by
`setDefaultTTL(secondsOrNull)`. Do not automatically retry writes after a network error; the write may have committed. The router
has no TLS/authentication yet, so use localhost only.
