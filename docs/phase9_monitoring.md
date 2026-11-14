# Phase 9 — Router performance metrics and monitoring

This phase adds a read-only router command `METRICS` and shows its data in the existing **black-and-white dashboard**. No extra services or Python/Node dependencies.

## Data shown

| Field | Interpretation |
|---|---|
| `requests_total`, `requests_ok`, `requests_err` | Counters for application commands since manager startup |
| `rps_10s` | Average requests/sec over a recent (maximum 10-second) window |
| `recent_requests`, `recent_errors`, `error_rate_10s_pct` | Most recent 10 seconds, where an `ERR...` response is an error |
| `avg_us` | Average synchronous router-processing time, microseconds |
| `get_count`, `get_avg_us` | GET request count and average router-processing latency |
| `set_count`, `set_avg_us` | SET request count and average router-processing latency |
| `p95_us_le` | Upper bound of the approximate **lifetime** 95th percentile latency histogram. Zero with requests > 0 denotes a value >1 second |
| `uptime_s` | Seconds since the cluster manager's router was created |

The metrics exclude `PING`, `COUNT`, `CLUSTER STATUS`, `OSSTATS`, `ALLOCSTATS`, and `METRICS` requests so dashboard polling doesn't produce fictitious application traffic. Other commands, including invalid commands, are counted. Requests rejected by connection-level limits before parsing aren't included. Both read and write latency reflect **router handling** (including synchronous storage-node RPC), **not** end-to-end client network latency. The 10-second view is bucketed in whole seconds, so rates at a bucket boundary are approximate. Metrics are in memory and reset when the manager restarts. Histograms have bounded memory. The dashboard sparkline keeps recent samples only in the browser.

Existing `CLUSTER STATUS` and `OSSTATS` already display node and replica status, memory budgets, RSS, restarts and promotions. The Phase 9 dashboard reads those as before and adds a metrics panel; it does not poll or modify stored keys for its graph.

## Install on your Mac

1. Stop the cluster using **Stop Cluster** on the dashboard, and exit the dashboard Python process (Ctrl+C in its Terminal). Leave `cluster-data` untouched.
2. Download and unzip the Phase 9 archive into the repository, then apply its patch once:

```bash
cd ~/Desktop/mini_redis
unzip -o ~/Downloads/fastkv_phase9_monitoring.zip -d .
git apply --check fastkv_phase9/metrics_dashboard.patch && git apply fastkv_phase9/metrics_dashboard.patch
cmake --build build-debug -j4
ctest --test-dir build-debug --output-on-failure
python3 tests/test_metrics_phase9.py ./build-debug/cluster-manager ./build-debug/fast-kv
```

3. Start the dashboard (`python dashboard/app.py`) and then Start Cluster. If the dashboard was open, reload with Cmd+Shift+R.

```bash
printf 'METRICS\n' | nc -w 3 127.0.0.1 7001
python3 examples/phase9_load.py
```

Watch the Monitoring section in `http://127.0.0.1:8765` while the example runs.

For regressions, stop the cluster first and run:

```bash
python3 tests/test_ttl_cluster.py ./build-debug/cluster-manager ./build-debug/fast-kv
python3 tests/test_dashboard.py ./build-debug/cluster-manager ./build-debug/fast-kv
python3 tests/test_sdk_phase8_live.py ./build-debug/cluster-manager ./build-debug/fast-kv
```

**Important:** The dashboard is localhost-only and not ready for the public internet. These are useful development diagnostics, not production SLAs, durable monitoring or an accurate benchmark of the full distributed system. Do not interpret the per-command average as P95; histogram P95 is an approximate upper bucket bound across *all* application operations.
