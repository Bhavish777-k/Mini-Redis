#!/usr/bin/env python3
"""End-to-end dashboard smoke test, using an isolated temporary cluster directory.

Usage: python3 tests/test_dashboard.py ./build-debug/cluster-manager ./build-debug/fast-kv
Ports 7001, 6381, 7381 must be free. Does not touch your real cluster-data.
"""
from __future__ import annotations
import http.client
import json
import os
import shutil
import socket
import sys
import tempfile
import threading
import time
from pathlib import Path
from http.server import ThreadingHTTPServer

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
from dashboard.app import Controller, Handler, HOST, parse_stats, wire  # noqa: E402


def request(port, method, path, data=None, token=None, origin=None):
    connection = http.client.HTTPConnection('127.0.0.1', port, timeout=10)
    headers = {}
    if data is not None:
        headers['Content-Type'] = 'application/json'
        if token:
            headers['X-CSRF-Token'] = token
        if origin:
            headers['Origin'] = origin
    connection.request(method, path, body=json.dumps(data) if data is not None else None, headers=headers)
    reply = connection.getresponse()
    raw = reply.read()
    connection.close()
    return reply.status, json.loads(raw)


def check(condition, message):
    if not condition:
        raise AssertionError(message)
    print('PASS:', message)


def main():
    if len(sys.argv) != 3:
        raise SystemExit('Usage: test_dashboard.py PATH_TO_MANAGER PATH_TO_FAST_KV')
    manager, node = [Path(x).resolve() for x in sys.argv[1:]]
    if not manager.is_file() or not node.is_file():
        raise SystemExit('Build the project first')
    for port in (7001, 6381, 7381):
        with socket.socket() as s:
            if s.connect_ex(('127.0.0.1', port)) == 0:
                raise SystemExit(f'Port {port} is busy. Stop your other cluster first.')
    with tempfile.TemporaryDirectory(prefix='fastkv-dashboard-test-') as tmp:
        root = Path(tmp)
        (root / 'dashboard').mkdir()
        (root / 'build-debug').mkdir()
        shutil.copy2(manager, root / 'build-debug/cluster-manager')
        shutil.copy2(node, root / 'build-debug/fast-kv')
        controller = Controller(root=root)
        server = ThreadingHTTPServer((HOST, 0), Handler)
        server.controller = controller
        port = server.server_port
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            status, response = request(port, 'GET', '/api/status')
            check(status == 200 and not response['online'], 'initial state offline')
            status, response = request(port, 'GET', '/api/session')
            token = response['csrf']
            check(status == 200 and len(token) > 20, 'session token available')
            config = {'threshold':60,'capacity':4096,'max_nodes':2,'replicas':1}
            status, response = request(port, 'POST', '/api/start', config)
            check(status == 403, 'start blocked without CSRF token')
            status, response = request(port, 'POST', '/api/start', config, token,
                                       origin='http://malicious.example')
            check(status == 403, 'cross-origin mutation blocked')
            status, response = request(port, 'POST', '/api/start', config, token)
            check(status == 200 and response['data']['online'], 'starts a replicated cluster')
            status, info = request(port, 'GET', '/api/status')
            check(status == 200 and info['node_count'] == 1 and info['replication'], 'correct primary/replica topology')
            check(info['nodes'][0].get('replica_state') == 'ready', 'standby ready')
            for action, key, value, expected in [
                ('SET','city','gandhinagar','OK'),
                ('GET','city',None,'gandhinagar'),
                ('WHERE','city',None,'6381')]:
                payload = {'action':action,'key':key}
                if value is not None:payload['value']=value
                status, response = request(port, 'POST', '/api/key', payload, token)
                check(status == 200 and response['data']['reply'] == expected, f'{action} routed correctly')
            status, response = request(port, 'POST', '/api/key',
                                       {'action':'SET','key':'bad key','value':'x'},token)
            check(status == 409, 'invalid key rejected')
            status, response = request(port, 'POST', '/api/resize', {'port':6381,'capacity':8192}, token)
            check(status == 200 and '8192' in response['data']['message'], 'live resize succeeds')
            status, response = request(port, 'GET', '/api/status')
            check(response['nodes'][0]['capacity']==8192 and response['nodes'][0]['replica_capacity']==8192,
                  'resize mirrored to standby')
            status, response = request(port, 'POST', '/api/resize', {'port':6381,'capacity':2048}, token)
            check(status==409, 'decreasing capacity is rejected')
            status, response = request(port, 'GET', '/api/logs')
            check(status == 200 and any('ROUTER listening' in x for x in response['lines']), 'manager logs accessible')
            status, response = request(port, 'POST', '/api/stop', {}, token)
            check(status == 200 and response['data']['stopped'], 'graceful shutdown')
            deadline = time.monotonic()+3
            while controller.ping() and time.monotonic() < deadline:time.sleep(.1)
            check(not controller.ping(), 'router stopped')
            print('ALL DASHBOARD SMOKE TESTS PASSED')
        finally:
            controller.close()
            server.shutdown()
            server.server_close()
            thread.join(timeout=3)


if __name__ == '__main__':
    main()
