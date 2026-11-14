# Installation and quick start

Fast-KV is a distributed in-memory caching engine with a command-line launcher, cluster dashboard, and Python/Node.js SDKs.

## Requirements

- macOS or Linux
- CMake 3.20+, a C++20 compiler, and Python 3.9+
- Node.js 18+ only for the optional JavaScript SDK

## Install

From the project root:

```bash
bash scripts/install_local.sh
```

The installer builds the engine and creates `~/.local/bin/fastkv`. To add that directory to your macOS shell PATH, put this in `~/.zprofile`:

```bash
export PATH="$HOME/.local/bin:$PATH"
```

Then open a new terminal. Alternatively, run `./bin/fastkv` from the repository.

## Run Fast-KV

```bash
fastkv start
fastkv status
fastkv dashboard
fastkv stop
fastkv shutdown
```

`start` launches the dashboard when needed and starts a cluster using the saved settings. `status` shows cluster health and capacity. `dashboard` opens the web UI at `http://127.0.0.1:8765`. `stop` stops storage processes and preserves data. `shutdown` additionally stops the launcher-managed dashboard. `logs` displays recent manager events.

Configure the cache explicitly:

```bash
fastkv start --capacity-mb 128 --max-nodes 3 --threshold 70 --replicas 1
```

For new installations, defaults are 64 MiB per node, a 60% scale-out threshold, up to 3 primary nodes, and 1 replica per primary. Existing installations use saved cluster settings. `start` can reuse saved data without resetting the current cache.

Scale-in is not implemented. Keep `--max-nodes` at least as large as the number of saved primary shards. To increase an existing node's capacity, use **Cluster Control → Increase node memory** in the dashboard.

## SDKs

Python:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --no-cache-dir ./sdk/python
```

```python
from fastkv import FastKV

cache = FastKV(port=7001)
cache.set("product:101", "cached", ttl=300)
print(cache.get("product:101"))
```

Node.js (run from the project root):

```js
const { FastKV } = require('./sdk/node');

async function main() {
  const cache = new FastKV();
  await cache.set('product:101', 'cached', { ttl: 300 });
  console.log(await cache.get('product:101'));
}
main().catch(console.error);
```

## Tests

```bash
cmake --build build-debug -j4
ctest --test-dir build-debug --output-on-failure
python3 tests/test_easy_install.py ./build-debug/cluster-manager ./build-debug/fast-kv
```

Stop the main cluster/dashboard before running integration tests that use its ports.

## Compatibility and deployment

- The current line-based protocol accepts whitespace-free keys and values; standard Redis RESP clients are not supported.
- The default deployment binds to loopback and does not provide API-key authentication or TLS. Restrict access to trusted hosts or place appropriate network controls in front of any remote deployment.
- The launcher manages processes from the current user session; it is not a system service.
- Offline backup and restore require the cluster to be stopped.
