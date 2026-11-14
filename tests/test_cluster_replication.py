"""Fast-KV opt-in replica/failover smoke tests. Run with manager and server paths.
Uses TCP ports 7000, 6381/6382, 7381/7382; run with no existing manager.
"""
import os
import pathlib
import re
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time


def ask(port, line, timeout=3):
    with socket.create_connection(('127.0.0.1', port), timeout=timeout) as sock:
        sock.sendall((line + '\n').encode())
        sock.settimeout(timeout)
        data = bytearray()
        while not data.endswith(b'\n'):
            chunk = sock.recv(8192)
            if not chunk:
                raise RuntimeError(f'no reply to {line!r} port={port}')
            data += chunk
        return data[:-1].decode()


def await_true(condition, seconds=8):
    finish = time.monotonic() + seconds
    last = None
    while time.monotonic() < finish:
        try:
            if condition():
                return
        except (OSError, ValueError, RuntimeError) as e:
            last = e
        time.sleep(.05)
    raise AssertionError(f'timed out: {last}')


def pid(status):
    return int(re.search(r' pid=(\d+)', status).group(1))


def start(manager, server, cwd, log):
    return subprocess.Popen([manager, server, '95', '4096', '2', '1'], cwd=cwd,
                            stdout=log, stderr=subprocess.STDOUT, start_new_session=True)


def stop(process):
    if process.poll() is None:
        os.killpg(process.pid, signal.SIGTERM)
    try: process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGKILL)
        process.wait(timeout=5)


def run(manager, server):
    manager = str(pathlib.Path(manager).resolve())
    server = str(pathlib.Path(server).resolve())
    with tempfile.TemporaryDirectory(prefix='fastkv_replication_') as root:
        root = pathlib.Path(root)
        with (root / 'cluster.log').open('w+') as log:
            proc = start(manager, server, root, log)
            try:
                await_true(lambda: ask(7000, 'PING') == 'PONG')
                status = ask(7000, 'CLUSTER STATUS')
                assert 'replica=7381' in status, status
                assert ask(7000, 'SET city old') == 'OK'
                allocation = ask(7000, 'ALLOCSTATS')
                assert 'node=6381 slab_reserved_bytes=' in allocation, allocation
                assert 'replica=7381 slab_reserved_bytes=' in allocation, allocation
                assert 'slab_internal_waste_bytes=' in allocation, allocation
                assert ask(7381, 'GET city') == 'old', 'replica must receive SET'
                assert ask(7000, 'INCR counter') == '1'
                assert ask(7381, 'GET counter') == '1'
                assert ask(7000, 'DEL counter') == '1'
                assert ask(7381, 'EXISTS counter') == '0'
                print('PASS: mirrored SET, INCR, DEL')

                os.kill(pid(status), signal.SIGKILL)
                await_true(lambda: 'promotions=1' in ask(7000, 'CLUSTER STATUS'))
                assert ask(7000, 'GET city') == 'old'
                assert ask(7000, 'WHERE city') == '7381'
                await_true(lambda: ask(6381, 'GET city') == 'old')
                print('PASS: primary killed, replica promoted, stale primary rebuilt')

                assert ask(7000, 'SET city newest') == 'OK'
                assert ask(6381, 'GET city') == 'newest'
                status = ask(7000, 'CLUSTER STATUS')
                assert 'port=7381' in status and 'replica=6381' in status
                os.kill(pid(status), signal.SIGKILL)
                await_true(lambda: 'promotions=2' in ask(7000, 'CLUSTER STATUS'))
                assert ask(7000, 'GET city') == 'newest'
                print('PASS: second failover preserves post-promotion writes')
            finally:
                stop(proc)
            # Process restart must preserve promoted-primary marker + data.
            proc = start(manager, server, root, log)
            try:
                await_true(lambda: ask(7000, 'PING') == 'PONG')
                assert ask(7000, 'GET city') == 'newest'
                assert ask(7381, 'GET city') == 'newest'
                print('PASS: manager restart recovers primary and replica')
                assert ask(7000, 'SET growing ' + 'x'*1600) == 'OK'
                assert ask(7000, 'SET big ' + 'y'*2600) == 'OK'
                status = ask(7000, 'CLUSTER STATUS')
                assert 'nodes=2' in status and 'replica=7382' in status, status
                assert ask(7382, 'GET big') == 'y'*2600
                print('PASS: scale-out creates replica for new shard')
                assert ask(7000, 'SET huge ' + 'a'*5000) == 'ERR key exceeds node capacity'
                assert ask(7000, 'GET city') == 'newest'
                print('PASS: oversize rejection leaves existing data untouched')
                # Losing only a standby does not require primary promotion.
                old_replica = int(re.search(r'replica_pid=(\d+)', status).group(1))
                os.kill(old_replica, signal.SIGKILL)
                await_true(lambda: ask(7381, 'GET city') == 'newest')
                assert ask(7000, 'SET city alive') == 'OK'
                assert ask(7381, 'GET city') == 'alive'
                print('PASS: crashed standby is resynchronized and writes resume')
                # Owner-controlled resize should apply to both copies.
                finished = subprocess.run([manager, 'resize', '6381', '8192'], cwd=root,
                                          text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                assert finished.returncode == 0, (finished.stdout, finished.stderr)
                assert 'max_bytes=8192' in ask(6381, 'STATS')
                assert 'max_bytes=8192' in ask(7381, 'STATS')
                print('PASS: owner resize applies to active and replica')
            finally:
                stop(proc)
        print('ALL REPLICATION SMOKE TESTS PASSED')


if __name__ == '__main__':
    if len(sys.argv) != 3:
        raise SystemExit('Usage: python3 tests/test_cluster_replication.py PATH_MANAGER PATH_FAST_KV')
    run(sys.argv[1], sys.argv[2])
