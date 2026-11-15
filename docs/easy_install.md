# Install and run Fast-KV

## Requirements

- macOS or Linux
- C++20 compiler and CMake 3.20+
- Python 3.9+
- Node.js 18+ only for the optional Node.js SDK

## Installation

Clone this repository and run:

```bash
bash scripts/install_local.sh
```

The installer compiles the engine and symlinks `fastkv` into `~/.local/bin`. Use `~/.local/bin/fastkv` directly, or add that directory to `PATH`:

```bash
export PATH="$HOME/.local/bin:$PATH"
```

On macOS, add this to `~/.zprofile` for future terminal sessions.

## Start the cache

```bash
fastkv start
fastkv status
fastkv dashboard
```

The router listens on `127.0.0.1:7001`; the dashboard uses `http://127.0.0.1:8765`.

A new installation defaults to 64 MiB per node, a 60% scale-out threshold, up to three primary nodes, and one replica per primary. Existing installations reuse the saved configuration. Customize the settings using:

```bash
fastkv start --capacity-mb 128 --max-nodes 3 --threshold 70 --replicas 1
```

Stop storage processes while preserving their data:

```bash
fastkv stop
```

Stop the cluster and a dashboard launched by `fastkv`:

```bash
fastkv shutdown
```

Use `fastkv logs` to display recent events or `fastkv logs --dashboard` to inspect dashboard startup output. The dashboard's **Cluster Control** panel can raise a node's memory limit and edit the default key expiration policy.

## Connect an application

Install the Python SDK:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --no-cache-dir ./sdk/python
```

```python
from fastkv import FastKV

cache = FastKV(port=7001)
cache.set("session:101", "active", ttl=1800)
print(cache.get("session:101"))
```

For Node.js, see [Node.js SDK](../sdk/node/README.md). For a full cache-aside workflow, see [the example](../examples/cache_aside.py).

## Verification

```bash
cmake --build build-debug -j4
ctest --test-dir build-debug --output-on-failure
python3 tests/test_dashboard_layout.py
python3 tests/test_sdk_phase8.py
(cd sdk/node && npm test)
```

Integration tests require their network ports to be free. Stop your main cluster and dashboard before executing them.

## Operational notes

The launcher manages processes for the current user session, not as a system service. Configuration and append-only storage are retained between restarts. Backup and restore are offline operations. Fast-KV uses a custom line protocol and does not accept Redis RESP clients. Without authentication or TLS, keep its endpoints on trusted networks with appropriate isolation; the bundled setup binds to loopback.
