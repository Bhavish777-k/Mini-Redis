#!/usr/bin/env python3
"""Phase 9 router metrics + dashboard integration in an isolated cluster directory.
Stop any local cluster first: TCP 7001, 6381 and 7381 must be free.
"""
from __future__ import annotations

import os
import pathlib
import re
import signal
import socket
import subprocess
import sys
import tempfile
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from dashboard.app import Controller, parse_metrics


def ask(text):
    with socket.create_connection(('127.0.0.1', 7001), timeout=3) as s:
        s.settimeout(3)
        s.sendall((text + '\n').encode())
        data = b''
        while b'\n' not in data:
            part = s.recv(8192)
            if not part:
                raise RuntimeError('Router closed connection')
            data += part
        return data.split(b'\n', 1)[0].decode()


def until(predicate, timeout=8):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        try:
            if predicate():
                return
        except (OSError, ValueError, RuntimeError):
            pass
        time.sleep(0.05)
    raise AssertionError('timeout waiting for condition')


def run(manager, server):
    for port in (7001, 6381, 7381):
        with socket.socket() as s:
            if s.connect_ex(('127.0.0.1', port)) == 0:
                raise SystemExit(f'Port {port} busy — stop the dashboard cluster before this test')
    manager = pathlib.Path(manager).resolve()
    server = pathlib.Path(server).resolve()
    with tempfile.TemporaryDirectory(prefix='fastkv-metrics-p9-') as directory:
        process = subprocess.Popen([str(manager), str(server), '95', '4096', '2', '1'],
                                   cwd=directory, stdout=subprocess.DEVNULL,
                                   stderr=subprocess.STDOUT, start_new_session=True)
        try:
            until(lambda: ask('PING') == 'PONG')
            start = parse_metrics(ask('METRICS'))
            assert start['requests_total'] == 0 and start['rps_10s'] == 0
            for command in ('PING', 'CLUSTER STATUS', 'COUNT', 'OSSTATS', 'METRICS'):
                ask(command)
            assert parse_metrics(ask('METRICS'))['requests_total'] == 0
            assert ask('SET phase9 value') == 'OK'
            assert ask('GET phase9') == 'value'
            assert ask('GET missing') == '(nil)'
            assert ask('EXPIRE phase9 nonsense').startswith('ERR')
            assert ask('INCR counter') == '1'
            sample = parse_metrics(ask('METRICS'))
            assert sample['requests_total'] == 5, sample
            assert sample['requests_ok'] == 4 and sample['requests_err'] == 1, sample
            assert sample['get_count'] == 2 and sample['set_count'] == 1, sample
            assert sample['rps_10s'] > 0 and sample['recent_errors'] == 1, sample
            assert sample['error_rate_10s_pct'] == 20.0, sample
            assert sample['p95_us_le'] >= 0
            print('PASS: METRICS throughput, per-command latency, errors, and poll exclusion')

            controller = Controller(root=pathlib.Path(directory))
            status = controller.status()
            assert status['online'] and status['metrics']['requests_total'] == 5, status
            assert status['node_count'] == 1 and status['replication'], status
            assert status['nodes'][0]['replica_state'] == 'ready', status
            assert parse_metrics(ask('METRICS'))['requests_total'] == 5
            print('PASS: dashboard status includes metrics, memory, and healthy replica')

            primary_pid = int(re.search(r' pid=(\d+)', ask('CLUSTER STATUS')).group(1))
            os.kill(primary_pid, signal.SIGKILL)
            until(lambda: 'promotions=1' in ask('CLUSTER STATUS'))
            assert ask('GET phase9') == 'value'
            assert parse_metrics(ask('METRICS'))['requests_total'] == 6
            print('PASS: router metrics and data remain readable after replica promotion')
        finally:
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGTERM)
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait(timeout=5)
    print('ALL PHASE 9 METRICS INTEGRATION TESTS PASSED')


if __name__ == '__main__':
    if len(sys.argv) != 3:
        raise SystemExit('Usage: test_metrics_phase9.py PATH_MANAGER PATH_STORAGE_SERVER')
    run(sys.argv[1], sys.argv[2])
