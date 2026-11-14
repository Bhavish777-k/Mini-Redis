"""Exercise Python client, CLI and Node client against the real C++ cluster.

Usage: python3 tests/test_sdk_phase8_live.py ./build-debug/cluster-manager ./build-debug/fast-kv
The dashboard cluster must be STOPPED first: ports 7001/6381/7381 are fixed.
No user cluster-data is touched (TemporaryDirectory is the working dir).
"""
import os
import pathlib
import re
import signal
import socket
import subprocess
import sys
import tempfile
import time

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'sdk' / 'python' / 'src'))
from fastkv import FastKV, FastKVCommandError


def wait_for_router(proc, timeout=12):
    db = FastKV(timeout=0.5)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            raise RuntimeError(f'cluster-manager exited with code {proc.returncode}')
        try:
            if db.ping():
                return
        except Exception:
            time.sleep(0.1)
    raise RuntimeError('cluster router not reachable on port 7001')


def run(manager, server):
    manager, server = str(pathlib.Path(manager).resolve()), str(pathlib.Path(server).resolve())
    if not pathlib.Path(manager).is_file() or not pathlib.Path(server).is_file():
        raise RuntimeError('First build binaries: cmake --build build-debug -j4')
    try:
        with socket.create_connection(('127.0.0.1', 7001), timeout=0.3):
            raise RuntimeError('Port 7001 is already in use — stop the dashboard cluster first')
    except OSError:
        pass

    with tempfile.TemporaryDirectory(prefix='fastkv_sdk8_') as tmp:
        log_path = pathlib.Path(tmp) / 'cluster.log'
        with log_path.open('w+') as log:
            proc = subprocess.Popen([manager, server, '95', '4096', '2', '1'],
                                    cwd=tmp, stdout=log, stderr=subprocess.STDOUT,
                                    start_new_session=True)
            try:
                wait_for_router(proc)
                db = FastKV()
                assert db.ping()
                assert db.set('sdk8:python', 'hello')
                assert db.get('sdk8:python') == 'hello'
                assert db.exists('sdk8:python')
                assert db.where('sdk8:python') in (6381, 6382, 7381, 7382)
                assert db.set('sdk8:counter', 8)
                assert db.incr('sdk8:counter') == 9
                assert db.set('sdk8:expire', 'temporary', ttl=2)
                assert 0 <= db.ttl('sdk8:expire') <= 2
                assert db.persist('sdk8:expire')
                assert db.ttl('sdk8:expire') == -1
                assert db.expire('sdk8:expire', 0)
                assert db.get('sdk8:expire') is None
                assert 'nodes=' in db.cluster_status()
                assert db.count() >= 2
                assert db.delete('sdk8:python')
                assert db.get('sdk8:python') is None
                try:
                    db.command('BADCOMMAND')
                except FastKVCommandError:
                    pass
                else:
                    raise AssertionError('router ERR not converted to SDK exception')
                print('PASS: Python SDK CRUD, TTL, counter, status, router errors')

                cli = subprocess.run([sys.executable, '-m', 'fastkv.cli', 'PING'],
                    cwd=tmp, env={**os.environ, 'PYTHONPATH': str(ROOT / 'sdk' / 'python' / 'src')},
                    text=True, capture_output=True, timeout=5)
                assert cli.returncode == 0 and cli.stdout.strip() == 'PONG', cli
                print('PASS: Python command-line interface')

                # Require Node for the full Phase 8 live test. No package install needed.
                node_script = """
const {FastKV} = require(process.argv[1]);
(async () => {
  const kv = new FastKV({port: 7001});
  if (!await kv.ping()) throw Error('PING');
  await kv.set('sdk8:node', 'hello', {ttl: 30});
  if (await kv.get('sdk8:node') !== 'hello') throw Error('GET');
  const ttl = await kv.ttl('sdk8:node');
  if (ttl < 0 || ttl > 30) throw Error('TTL=' + ttl);
  if (!await kv.exists('sdk8:node')) throw Error('EXISTS');
  await kv.set('sdk8:ncounter', 1);
  if (await kv.incr('sdk8:ncounter') !== 2) throw Error('INCR');
  if (!await kv.persist('sdk8:node')) throw Error('PERSIST');
  if (await kv.ttl('sdk8:node') !== -1) throw Error('TTL after PERSIST');
  if (!await kv.delete('sdk8:node')) throw Error('DEL');
  if (await kv.get('sdk8:node') !== null) throw Error('GET missing');
  console.log('PASS: Node.js SDK CRUD, TTL, counter');
})().catch(e => { console.error(e); process.exit(1); });
"""
                try:
                    node = subprocess.run(['node', '-e', node_script, str(ROOT / 'sdk' / 'node')],
                        cwd=tmp, text=True, capture_output=True, timeout=15)
                except FileNotFoundError:
                    raise RuntimeError('Node.js 18+ required to run complete Phase 8 live test')
                if node.returncode:
                    raise RuntimeError(f'Node SDK failed:\n{node.stdout}\n{node.stderr}')
                print(node.stdout.strip())

                assert db.set('sdk8:survivor', 'kept')
                owner = db.where('sdk8:survivor')
                status = db.cluster_status()
                match = re.search(r'\bport=' + str(owner) + r'\s+\d+/\d+\s+pid=(\d+)', status)
                assert match, status
                old_pid = int(match.group(1))
                promotions_before = sum(int(v) for v in re.findall(r'\bpromotions=(\d+)', status))
                os.kill(old_pid, signal.SIGKILL)
                deadline = time.monotonic() + 8
                promoted = False
                while time.monotonic() < deadline:
                    try:
                        after = db.cluster_status()
                        promoted = sum(int(v) for v in re.findall(r'\bpromotions=(\d+)', after)) > promotions_before
                        if promoted and db.get('sdk8:survivor') == 'kept':
                            break
                    except Exception:
                        pass
                    time.sleep(0.1)
                else:
                    raise AssertionError('SDK data unavailable after simulated primary crash')
                assert db.get('sdk8:survivor') == 'kept'
                print('PASS: Python SDK routes to newly promoted primary after crash')
                print('ALL PHASE 8 LIVE INTEGRATION TESTS PASSED')
            finally:
                if proc.poll() is None:
                    os.killpg(proc.pid, signal.SIGTERM)
                try:
                    proc.wait(timeout=7)
                except subprocess.TimeoutExpired:
                    os.killpg(proc.pid, signal.SIGKILL)
                    proc.wait(timeout=7)
                if proc.returncode not in (0, -signal.SIGTERM):
                    log.flush()
                    print('Manager log:', log_path, file=sys.stderr)


if __name__ == '__main__':
    if len(sys.argv) != 3:
        raise SystemExit('Usage: test_sdk_phase8_live.py MANAGER_EXEC FASTKV_EXEC')
    run(sys.argv[1], sys.argv[2])
