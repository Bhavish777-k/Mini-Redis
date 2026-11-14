# Fast-KV Phase 6 — Owner Dashboard

**Additive source bundle.** Extract this archive in your `mini_redis` folder; it creates `dashboard/`, `docs/dashboard.md`, and `tests/test_dashboard.py`. It does not change your C++ code or CMakeLists.txt.

### macOS quick install

```sh
cd ~/Desktop/mini_redis
unzip -o ~/Downloads/fastkv_dashboard_phase6.zip -d .
cmake --build build-debug -j4
python3 tests/test_dashboard.py ./build-debug/cluster-manager ./build-debug/fast-kv
python3 dashboard/app.py
```

Open http://127.0.0.1:8765

**If the test reports busy ports**, stop your previously running manager and try again. Dashboard smoke tests never delete your actual `cluster-data/`.

After tests pass:

```sh
git add dashboard/ tests/test_dashboard.py docs/dashboard.md
git commit -m "Add local cluster management dashboard"
```

Further details: `docs/dashboard.md`.
