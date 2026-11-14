# Phase 11 — Key Browser + Optional TTL

Fast-KV's local-only dashboard now offers a visual browser for keys across active primary shards. It does not require knowing which node stores each key. This is a developer prototype, **not** an authenticated public database console.

## Features

- **Browse and search** keys by case-sensitive *prefix*. The UI loads at most 15 keys per page and shows remaining TTL and owner port. Next/Previous use lexicographic key cursors.
- **Inspect/edit** stored values. Selecting a key shows its value, current TTL, and owner. Edits require selecting the existing key; a new-key form refuses to overwrite an existing key accidentally.
- **Manual TTL (enhanced in Phase 11.1):** Database default (new keys), Keep existing TTL (edits), explicit Never expire, 5 minutes, 1 hour, 24 hours, or a positive custom duration (seconds, maximum 3,153,600,000). A key with no TTL remains until deleted or evicted.
- **TTL-only update:** *Apply TTL only* uses `EXPIRE` or `PERSIST`, without changing values. *Save key* uses one `SET` request with `EX`, `PERSIST` or `KEEPTTL`, or no option to inherit the database default.
- **Delete:** asks for confirmation. The backend requires the exact key as confirmation.

## Start / usage

1. Stop cluster in the dashboard; stop `dashboard/app.py` with `Ctrl+C` before rebuilding. **Do not delete `cluster-data`.**
2. Rebuild both C++ binaries after applying the Phase 11 patch: `cmake --build build-debug -j4`.
3. Run the isolated test while the router and storage ports are free:
   ```sh
   python3 tests/test_key_browser_phase11.py ./build-debug/cluster-manager ./build-debug/fast-kv
   ```
4. Start the dashboard with `python3 dashboard/app.py`, open `http://127.0.0.1:8765`, start your existing cluster, and choose **Key Browser**. Refresh the page with `Cmd+Shift+R` if your browser cached the old JavaScript.
5. To create an expiring key, enter `session:101` and `active`, select **1 hour**, click **Save key**. Open the key to inspect TTL or select **Never expire → Apply TTL only** to keep the value permanently (subject to eviction).

## Router SCAN protocol

Phase 11 adds an internal browser cursor command across primary shards:

```text
SCAN - 15 -
SCAN <hex_cursor> 15 <hex_utf8_prefix>
```

Response:

```text
next=<hex_cursor_or_-> count=<n> key=<hex_utf8_key> key=<hex_utf8_key> ...
```

- Hex cursor/prefix protects the newline-delimited TCP protocol; `-` means the beginning or no prefix. The limit is 1–50 per request.
- Each storage node returns a bounded sorted slice. The router merges slices, omits expired keys, and produces a forward cursor. The key list is **best-effort**, not a transactional snapshot: concurrent writes, deletions, or TTL changes can affect which keys appear across pages.
- Scanning examines keys on each node per page: it is **O(number of keys)** work per request even though response size is bounded. Optimize with persistent per-shard ordered indexes if you later support very large deployments.
- This text-only browser lists keys with up to 120 UTF-8 bytes and no ASCII space/control characters. Other keys remain accessible through existing database operations but may not appear in the browser; binary/non-UTF-8 keys are not supported in the UI.

## Important limits and safety

- **TTL is not hardcoded.** Optional expiration is chosen for each key; it can be changed later.
- **Plain `SET` resets expiration to the current database default**; `SET ... KEEPTTL` preserves the previous absolute deadline for an existing key. The key browser selects Keep when opening an existing key.
- Phase 11.1 uses a **single router SET operation** and an on-disk intent reconciled after manager restart. Strict durability in the face of sudden power failure is not yet guaranteed.
- The one-token wire protocol does not currently support values with spaces, multiline text, or arbitrary binary values.
- The browser is for **trusted localhost development only**. Authentication, access control, TLS, and public hosting remain Phase 12 and later work.
- The tests operate in a temporary directory and require free ports 7001, 6381 and 7381; do not run them against your active cluster.
