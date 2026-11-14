# Fast-KV Python SDK + CLI (Phase 8)

Install locally from the project root:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e ./sdk/python
```

```python
from fastkv import FastKV

db = FastKV('127.0.0.1', port=7001)
db.set('username', 'awnish')
print(db.get('username'))
db.set('session:101', 'active', ttl=60)
print(db.ttl('session:101'))
print(db.cluster_status())
```

Interactive shell: `fastkv-cli` or `python3 -m fastkv`.

One-shot: `fastkv-cli GET username` or `fastkv-cli --command 'CLUSTER STATUS'`.

The SDK uses **one TCP connection per command** to the **router**, not individual
storage node ports. Only whitespace-free keys and values are supported by the
current server protocol. `get()` maps `(nil)` to `None`, so the literal value
`(nil)` is ambiguous. `set(..., ttl=...)` uses one router `SET ... EX`
operation, with manager-restart intent recovery (not strict power-loss atomicity).
`set(..., persist=True)` makes a key permanent; `set(..., keep_ttl=True)`
retains an existing deadline; a plain `set()` inherits the database default,
configured with `set_default_ttl(seconds_or_None)`. Never automatically retry mutations after a network failure:
the write outcome may be unknown. Local self-hosted use only; no auth/TLS yet.
