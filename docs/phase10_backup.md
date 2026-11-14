# Phase 10 — Offline Backup and Restore

**Scope:** local single-host Fast-KV prototype. This feature creates a **stopped-cluster filesystem snapshot**. It is **not** a hot backup, remote backup, or production disaster-recovery guarantee.

## What's preserved

* `cluster-data` node/replica `data/appendonly.log` files, `capacity.bytes`, shard promotion markers, router migration journal, and expiration metadata (absolute TTL deadlines).
* `dashboard/.last_config.json` if present (startup settings).
* SHA-256 and byte length for every file in `manifest.json`. The ZIP is verified before it is published and before restore. Hashes detect accidental corruption; they are not cryptographic authentication against a malicious party who can rewrite both the ZIP and its manifest.
* The previously active `cluster-data` directory is **renamed into `backups/cluster-data-before-restore-...`**, and the previous saved dashboard config is preserved there too. Never remove these until you have verified the restored cluster.

Runtime `manager.lock` and `resize.lock` files are excluded, then a fresh lock is prepared on restore. Temporary storage files (`.tmp`, `.copying`) and symlinks are rejected to avoid backing up an inconsistent state.

## CLI quick start

**Stop Cluster** in the local dashboard (or stop your standalone cluster manager). Stop means the router and storage workers are no longer running; there is no online backup yet.

```bash
cd ~/Desktop/mini_redis
python3 tools/fastkv_backup.py create
python3 tools/fastkv_backup.py list
python3 tools/fastkv_backup.py verify fastkv-backup-YYYYMMDD-HHMMSS-xxxxxxxx.zip
python3 tools/fastkv_backup.py restore fastkv-backup-YYYYMMDD-HHMMSS-xxxxxxxx.zip --confirm RESTORE
```

Replace the example filename with one from `list`. `restore` requires exact `--confirm RESTORE`, rejects running clusters, and keeps previous data in `backups/`. Reopen the dashboard and start the cluster using the restored saved configuration. Original TTL deadlines do not restart or extend; keys whose deadlines elapsed while the cluster was stopped remain expired.

## Dashboard

1. Open `http://127.0.0.1:8765`. Select **Stop Cluster** before snapshot/restore.
2. Scroll to **Backups** (or use sidebar), then select **Create verified backup**.
3. Select an archive and click **Verify archive** to rehash it (allowed while cluster is running).
4. For restore, stop the cluster, select an archive, type **RESTORE** and confirm the browser prompt.
5. Start the cluster again. Check `GET`, `TTL`, `CLUSTER STATUS` and replica health.

The dashboard is localhost-only and uses a CSRF token; it is not authenticated for remote or multi-user access. Do not forward port 8765 to the internet.

## Safety, limitations, and recovery

* Operations refuse to run if the cluster manager holds its `flock` lock or the known router/node ports accept connections. The manager and backup tool coordinate on `cluster-data/manager.lock`. Keep unrelated processes away from Fast-KV's reserved ports.
* Both backup and restore use extra disk space. The snapshot keeps all node and replica logs. Do not perform a restore if the disk is nearly full.
* A backup is a point-in-time snapshot taken **after** shutdown, not a live consistent-snapshot protocol; do not edit `cluster-data` during the operation.
* Restore stages and verifies files before changing `cluster-data`, retaining a rollback folder. A sudden power failure mid-swap can still require manual recovery from `backups/cluster-data-before-restore-*`.
* The local ZIPs are **not encrypted** and may contain sensitive application data. Protect their filesystem permissions and do not publish them publicly.
* The project does not yet implement automated retention, scheduled backups, cloud backup, cross-version migrations, or zero-downtime restore.
* When an archive has no dashboard config, the existing dashboard configuration is left unchanged; only configs already saved by the dashboard can be restored.

## Tests

Stop the cluster first, then run:

```bash
python3 tests/test_backup_phase10.py ./build-debug/cluster-manager ./build-debug/fast-kv
python3 tests/test_dashboard.py ./build-debug/cluster-manager ./build-debug/fast-kv
```

Tests use isolated temporary directories, not your real `cluster-data`. The live tests briefly bind 7001, 6381, and 7381. Python 3.10+ and macOS/Linux are supported for this offline tool (`fcntl.flock`).

## Git hygiene

Do not commit backup ZIPs or preserved data folders. The included `backups/.gitignore` excludes the contents of `backups/` while keeping that ignore file tracked. Existing `cluster-data` is also intended to remain out of source control.
