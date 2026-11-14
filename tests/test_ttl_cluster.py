"""Integration smoke test for router-side TTL with replication, restart and failover.
Run only while no other manager is using ports 7001, 6381, and 7381.
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


def ask(text):
    with socket.create_connection(('127.0.0.1', 7001), timeout=2) as s:
        s.sendall((text + '\n').encode())
        s.settimeout(2)
        data = b''
        while not data.endswith(b'\n'):
            next_part = s.recv(8192)
            if not next_part:
                raise RuntimeError('Router connection closed without reply')
            data += next_part
        return data[:-1].decode()


def until(predicate, timeout=8):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        try:
            if predicate():
                return
        except (OSError, RuntimeError, ValueError):
            pass
        time.sleep(0.05)
    raise AssertionError('timeout waiting for condition')


def start(manager, server, wd):
    process = subprocess.Popen(
        [str(manager), str(server), '95', '4096', '2', '1'],
        cwd=wd, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT, start_new_session=True,
    )
    until(lambda: ask('PING') == 'PONG')
    return process


def stop(process):
    if process.poll() is None:
        os.killpg(process.pid, signal.SIGTERM)
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGKILL)
        process.wait(timeout=5)


def run(manager, server):
    manager, server = pathlib.Path(manager).resolve(), pathlib.Path(server).resolve()
    with tempfile.TemporaryDirectory(prefix='fastkv_ttl_') as wd:
        proc = start(manager, server, wd)
        try:
            assert ask('SET ttlkey hello') == 'OK'
            assert ask('TTL ttlkey') == '-1'
            assert ask('TTL missingkey') == '-2'
            assert ask('EXPIRE missingkey 5') == '0'
            assert ask('EXPIRE ttlkey nonsense').startswith('ERR ')
            assert ask('EXPIRE ttlkey 3') == '1'
            assert 0 <= int(ask('TTL ttlkey')) <= 3
            assert ask('GET ttlkey') == 'hello'
            current = ask('CLUSTER STATUS')
            primary_pid = int(re.search(r' pid=(\d+)', current).group(1))
            os.kill(primary_pid, signal.SIGKILL)
            until(lambda: 'promotions=1' in ask('CLUSTER STATUS'))
            assert ask('GET ttlkey') == 'hello'
            until(lambda: ask('GET ttlkey') == '(nil)', timeout=5)
            assert ask('TTL ttlkey') == '-2'
            assert ask('WHERE ttlkey') == '(nil)'
            assert ask('COUNT') == '0'
            print('PASS: TTL survives primary failover; expired values removed from replicas')

            assert ask('SET counter 1') == 'OK'
            assert ask('EXPIRE counter 6') == '1'
            assert ask('INCR counter') == '2'
            assert int(ask('TTL counter')) >= 0  # INCR keeps TTL
            assert ask('SET counter 5') == 'OK'
            assert ask('TTL counter') == '-1'  # SET clears TTL
            assert ask('EXPIRE counter 6') == '1'
            assert ask('PERSIST counter') == '1'
            assert ask('TTL counter') == '-1'
            assert ask('PERSIST counter') == '0'
            assert ask('EXPIRE counter 0') == '1'
            assert ask('GET counter') == '(nil)'
            print('PASS: EXPIRE, TTL, PERSIST, SET reset, INCR retain, immediate expiry')

            assert ask('SET restart stillhere') == 'OK'
            assert ask('EXPIRE restart 3') == '1'
            time.sleep(0.7)
        finally:
            stop(proc)
        proc = start(manager, server, wd)
        try:
            assert ask('GET restart') == 'stillhere'
            until(lambda: ask('GET restart') == '(nil)', timeout=5)
            assert ask('TTL restart') == '-2'
            print('PASS: absolute TTL deadline persists across manager restart')
        finally:
            stop(proc)
    print('ALL TTL INTEGRATION TESTS PASSED')


if __name__ == '__main__':
    if len(sys.argv) != 3:
        raise SystemExit('Usage: test_ttl_cluster.py PATH_MANAGER PATH_FAST_KV')
    run(sys.argv[1], sys.argv[2])
