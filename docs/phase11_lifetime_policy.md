# Phase 11.1 — Developer key-lifetime policy

Fast-KV is a **developer-facing key-value database**. The local control plane is a development/operations console, not an end-user application. A single database-level default TTL applies to new writes from the router, both SDKs, the interactive CLI and the dashboard. Developers can override it **per key**.

## Precedence

1. `SET key value EX seconds` sets an explicit expiration (`0` expires immediately).
2. `SET key value PERSIST` explicitly creates/overwrites a permanent key.
3. `SET key value KEEPTTL` retains the current **absolute deadline** when updating an existing key. If the key does not exist, it inherits the database default.
4. Plain `SET key value` inherits the current database default (`TTLDEFAULT GET`). Without a configured default, new keys are permanent. Overwriting an existing key with plain `SET` resets its old expiration to the current default.
5. `INCR key` preserves an existing key's deadline; a newly-created counter inherits the default.

Defaults change **future writes**, not existing TTLs. `EXPIRE`, `PERSIST` and `TTL` retain their existing meanings. This phase deliberately **does not implement bulk overwriting all existing TTLs**, since doing so could silently break developer-specified lifetimes.

## Manager/CLI commands

```text
TTLDEFAULT GET                  -> never (initially)
TTLDEFAULT SET 3600             -> OK (new writes inherit 1-hour TTL)
TTLDEFAULT SET never            -> OK (new writes permanent unless EX specified)
SET cache:1 value               -> OK (uses current default)
SET otp:1 123456 EX 300         -> OK (5 minutes, regardless of default)
SET config:1 enabled PERSIST    -> OK (always permanent)
SET cache:1 newvalue KEEPTTL    -> OK (preserve deadline if key exists)
TTL otp:1                       -> remaining seconds
EXPIRE otp:1 60                 -> 1 (change existing deadline)
PERSIST otp:1                   -> 1 (remove existing deadline)
```

The Python CLI (`fastkv-cli`) executes the same commands. You can also use `fastkv-cli --command 'TTLDEFAULT GET'`.

## Python SDK

```python
from fastkv import FastKV

db = FastKV(port=7001)
db.set_default_ttl(3600)           # owner/developer config, future writes only
assert db.get_default_ttl() == 3600

db.set('cache:1', 'payload')        # uses default TTL
db.set('otp:1', '123456', ttl=300) # explicit 5 minutes
db.set('settings:1', 'on', persist=True)  # explicitly never expire
db.set('cache:1', 'updated', keep_ttl=True) # preserve expiry timestamp
print(db.ttl('cache:1'))
db.set_default_ttl(None)           # revert to no default expiry
```

After applying the patch, **reinstall the Python package normally** (especially on the previously used Python 3.15 venv):

```bash
source .venv/bin/activate
python -m pip install --no-cache-dir ./sdk/python
```

## Node.js SDK

```js
const { FastKV } = require('./sdk/node');
const db = new FastKV({port: 7001});
await db.setDefaultTTL(3600);
await db.set('cache:1', 'payload');
await db.set('otp:1', '123456', {ttl: 300});
await db.set('settings:1', 'on', {persist: true});
await db.set('cache:1', 'updated', {keepTTL: true});
console.log(await db.getDefaultTTL());
```

The dashboard **Configuration → Developer key lifetime policy** sets the same default. **Key Browser** and **Key Console** offer “Database default”, “Keep existing TTL”, “Never expire”, duration presets and custom TTL. These are developer controls, not consumer UI.

## Persistence, backup and limitations

- The default TTL is saved at `cluster-data/default_ttl.meta`; absolute per-key deadlines remain in `cluster-data/expirations.meta` and follow keys during normal migrations/failovers.
- A single router-side `SET` command records a recoverable intent in `cluster-data/pending_lifetime_write` before modifying the data. On manager restart, an interrupted write is reconciled with its original absolute deadline.
- Offline backups include the policy automatically; backups refuse a pending unfinished lifetime write.
- **This remains a prototype**: it is not a proof of strict crash/power-loss atomicity. Metadata is saved using temporary files and rename, but this phase does not add fsync-based durability across all nodes, transactional guarantees, or network-partition consensus. Use locally and do not expose `TTLDEFAULT SET` on public interfaces before Phase 12 authentication.
- The wire protocol still supports only whitespace-free keys/values; changing the default on a live cluster does not update existing keys, even those that were previously created with the old default.
- Manager restart and replica promotion are exercised by integration tests; adversarial fault injection/power-off and multiple-manager split-brain scenarios require further work.
