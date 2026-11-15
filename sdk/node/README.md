# Fast-KV Node.js SDK

Dependency-free Node.js client for the Fast-KV router (Node.js 18+).

## Install

From the Fast-KV repository root:

```bash
npm install ./sdk/node
```

## Example

```js
const { FastKV } = require('fastkv-client');

async function main() {
  const cache = new FastKV({ host: '127.0.0.1', port: 7001 });
  await cache.set('product:101', 'cached', { ttl: 300 });
  console.log(await cache.get('product:101'));
  await cache.delete('product:101');
}

main().catch(console.error);
```

The client connects to the router with one TCP connection per command. Keys and values are single tokens without whitespace. `get()` maps `(nil)` to `null`, which makes the literal stored value `(nil)` ambiguous. Use `{ ttl }`, `{ persist: true }`, or `{ keepTTL: true }` to control expiration. Other writes inherit the cache's default TTL. Do not blindly retry a failed write: its outcome may be unknown.

See the repository [README](../../README.md) for setup and usage.
