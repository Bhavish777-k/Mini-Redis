# Phase 6 — Fast-KV Local Dashboard

A lightweight owner-facing dashboard for the existing Fast-KV cluster manager. Written with Python's standard library and plain HTML/CSS/JavaScript; no npm install or Python packages required.

## Requirements

- macOS or Linux (uses your existing C++ cluster-manager).
- Python 3.10 or later.
- Built binaries: `build-debug/cluster-manager` and `build-debug/fast-kv`.
- Ports `8765` (local dashboard), `7001` (router), and the storage ports must be available for a new cluster. If the cluster manager is already running on `7001`, the dashboard attaches in monitor mode.

## Quick start

```sh
cd ~/Desktop/mini_redis
cmake -S . -B build-debug
cmake --build build-debug -j4
python3 dashboard/app.py
```

Open **http://127.0.0.1:8765** in a browser.

If a cluster is already running independently, the dashboard will show it without restarting it. The dashboard only offers a Stop action for a cluster launched from its own process.

## What it can do

- Start a cluster with capacity per node, a maximum node count, a scaling threshold, and optional replication (one standby per shard).
- Display active primary/replica ports and PIDs, stored data utilization, primary restarts, failover promotions, and OS RSS (when available).
- Increase the memory budget of an existing node, via the existing local `cluster-manager resize` command. Decreases are intentionally rejected.
- Run a limited set of demo commands through the existing TCP router: `SET`, `GET`, `WHERE`, `INCR`, and `DEL`.
- Display dashboard activity and the cluster manager's recent output.

Cluster configuration applies to **starting** a manager. It is not a live change to `max_nodes` or the threshold. Live resizing applies only to node capacity.

## Verify before committing

If no other Fast-KV cluster is running, run:

```sh
python3 tests/test_dashboard.py ./build-debug/cluster-manager ./build-debug/fast-kv
```

The test uses a temporary directory for data and verifies startup, CSRF defense, replication topology, key operations, live resizing, logs, and shutdown. It uses local ports `7001`, `6381`, `7381`; stop any existing manager before running it.

Commit only the source files:

```sh
git add dashboard/ tests/test_dashboard.py docs/dashboard.md
git commit -m "Add local cluster management dashboard"
```

## Important constraints

- **Local-only prototype.** The HTTP listener is hard-bound to `127.0.0.1`. Do NOT put the dashboard or raw Fast-KV router on the public internet. It has no user accounts, TLS, multi-tenancy, secure role management, quotas, or durable audit trails.
- The manager stores/recovers data from `cluster-data/` under the repo. The dashboard does **not** clear or overwrite existing database files. An incompatible previous node-count or replication layout can prevent startup; inspect the manager logs rather than deleting data.
- The dashboard's node capacity is the logical KV budget, *not* the total OS process memory. RSS is measured separately via `OSSTATS`.
- The current Fast-KV text protocol accepts single-token keys and values. The form therefore rejects whitespace in values.
- OS-level cgroup resource enforcement is Linux-only; it is not activated by the dashboard.
- The startup defaults are for a small local demonstration (4 KiB/node, three nodes, 60% threshold, replication enabled), not for production.
- The manager's log and last settings are stored as ignored local files within `dashboard/`.
- Prefer the CLI for advanced cluster maintenance; do not treat this as a fully featured Redis Cloud equivalent.
