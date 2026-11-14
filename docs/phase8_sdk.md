# Phase 8 — Developer onboarding

## Requirements
- Fast-KV phase 7 router (localhost port **7001**) running via the dashboard or manager.
- Python 3.9+ for Python SDK and CLI.
- Node.js 18+ for Node SDK.

## Install (local, not published)

From the Fast-KV repository root:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e ./sdk/python
# To add Node SDK to another project, from that project's directory:
npm install /absolute/path/to/mini_redis/sdk/node
```

## Use

```bash
fastkv-cli
fastkv-cli SET username awnish
fastkv-cli GET username
fastkv-cli --command 'CLUSTER STATUS'
python3 examples/phase8_python.py
node examples/phase8_node.cjs
```

Node.js SDK:

```js
const {FastKV} = require('fastkv-client');
const db = new FastKV({port: 7001});
await db.set('username', 'awnish');
console.log(await db.get('username'));
```

Python SDK:

```py
from fastkv import FastKV

db = FastKV(port=7001)
db.set('username', 'awnish')
print(db.get('username'))
```

## API surface

| Python | Node.js | Return |
| --- | --- | --- |
| `.ping()` | `.ping()` | boolean (true for PONG) |
| `.set(key, value, ttl=60)` | `.set(key, value, {ttl:60})` | boolean |
| `.get(key)` | `.get(key)` | string or None/null |
| `.delete(key)` | `.delete(key)` | boolean |
| `.exists(key)` | `.exists(key)` | boolean |
| `.incr(key)` | `.incr(key)` | integer |
| `.expire(key, 60)` | `.expire(key, 60)` | boolean |
| `.ttl(key)` | `.ttl(key)` | seconds, -1 no expiry, -2 missing |
| `.persist(key)` | `.persist(key)` | boolean |
| `.where(key)` | `.where(key)` | primary port or None/null |
| `.count()` | `.count()` | total keys |
| `.cluster_status()` | `.clusterStatus()` | raw status string |
| `.os_stats()` | `.osStats()` | raw telemetry string |
| `.alloc_stats()` | `.allocStats()` | raw allocator telemetry string |
| `.command('PING')` | `.command('PING')` | raw reply string |

## Protocol boundaries — important

- Keys and values are **single whitespace-free tokens**; spaces/newlines and binary data are not supported by the existing server's line-based protocol.
- The `(nil)` sentinel makes a stored literal value `(nil)` indistinguishable from a missing key. Avoid that value until protocol v2.
- Phase 11.1 upgrades `set(..., ttl=...)` to one router `SET ... EX seconds` request with a recoverable manager-side write intent. This does not guarantee strict power-loss atomicity or multi-node transactions. Plain `set()` inherits the developer database default; `persist` and `keep_ttl`/`keepTTL` are explicit overrides.
- Reads and writes each make a **new TCP connection**; connection pooling is a later optimization.
- Never blindly retry failed mutation calls (`SET`, `INCR`, etc.): a lost reply does not mean the write failed.
- The current router is localhost-only and offers no authentication, TLS, or tenant isolation. Do **not** expose directly to the public internet.
- Package names and binaries still use the **temporary Fast-KV name**; these local packages are not published on npm/PyPI.

## Tests

With no other cluster using port 7001, run:

```bash
python3 tests/test_sdk_phase8.py
(cd sdk/node && npm test)
python3 tests/test_sdk_phase8_live.py ./build-debug/cluster-manager ./build-debug/fast-kv
```

The live test runs the real C++ manager in a temporary directory; it does not delete or alter your main `cluster-data` directory.
