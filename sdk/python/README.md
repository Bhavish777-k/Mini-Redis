# Fast-KV Python SDK and CLI

A dependency-free client for the Fast-KV router. Start Fast-KV before running your application.

## Installation

From the Fast-KV repository root:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --no-cache-dir ./sdk/python
```

## Example

```python
from fastkv import FastKV

cache = FastKV(port=7001)
cache.set("product:101", "cached", ttl=300)
print(cache.get("product:101"))
print(cache.ttl("product:101"))
cache.delete("product:101")
```

## CLI

```bash
fastkv-cli PING
fastkv-cli GET product:101
fastkv-cli --command 'CLUSTER STATUS'
```

The client opens one connection per command to the router (port `7001`). It supports single-token keys and values without whitespace. `get()` returns `None` for the protocol's `(nil)` response, so a literal stored value of `(nil)` is ambiguous.

Use `ttl=seconds` for explicit expiry, `persist=True` for no expiry, or `keep_ttl=True` to preserve an existing deadline. Without those options, `set()` uses the cache's configured default TTL. A failed network write can have an unknown outcome; check the value before retrying a mutation.

For installation and cache examples, see the repository [README](../../README.md).
