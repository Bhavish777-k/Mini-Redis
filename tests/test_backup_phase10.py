#!/usr/bin/env python3
"""Phase 10 offline backup+restore unit, dashboard HTTP, and real C++ cluster test.

Usage: python3 tests/test_backup_phase10.py ./build-debug/cluster-manager ./build-debug/fast-kv
The live part needs free ports 7001, 6381 and 7381; never touches local cluster-data.
"""
from __future__ import annotations

import fcntl
import http.client
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import zipfile
from pathlib import Path
from http.server import ThreadingHTTPServer

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from dashboard.backup_ops import (BackupError, archive_path, create_backup,
                                  list_backups, restore_backup, verify_archive)
from dashboard.app import Controller, Handler, HOST


def check(ok, msg):
    assert ok, msg
    print('PASS:', msg, flush=True)


def expect_error(fn, contains):
    try:
        fn()
    except BackupError as exc:
        assert contains.lower() in str(exc).lower(), (str(exc), contains)
    else:
        raise AssertionError(f'Expected BackupError containing {contains}')


def request(port, method, url, body=None, token=None):
    c = http.client.HTTPConnection('127.0.0.1', port, timeout=5)
    headers = {'Content-Type': 'application/json'}
    if token: headers['X-CSRF-Token'] = token
    c.request(method, url, body=None if body is None else json.dumps(body), headers=headers)
    r = c.getresponse(); payload = json.loads(r.read()); status=r.status; c.close()
    return status, payload


def unit_and_dashboard():
    with tempfile.TemporaryDirectory(prefix='fastkv-backup-unit-') as t:
        root = Path(t)
        (root / 'cluster-data/node-1/data').mkdir(parents=True)
        (root / 'cluster-data/replica-1/data').mkdir(parents=True)
        (root / 'dashboard').mkdir()
        original = b'SET favorite original\n'
        (root / 'cluster-data/node-1/data/appendonly.log').write_bytes(original)
        (root / 'cluster-data/replica-1/data/appendonly.log').write_bytes(original)
        (root / 'cluster-data/node-1/capacity.bytes').write_text('4096\n')
        (root / 'cluster-data/expirations.meta').write_text('test-absolute-timestamps\n')
        (root / 'dashboard/.last_config.json').write_text('{"max_nodes":2,"capacity":4096,"replicas":1,"threshold":60}\n')
        backup = create_backup(root)
        archive = archive_path(root, backup['name'])
        check(verify_archive(archive)['verified'] and len(list_backups(root)) == 1, 'offline create, list and SHA256 verify')
        # A manager with its lock held must block our snapshot.
        with (root / 'cluster-data/manager.lock').open('a+b') as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            expect_error(lambda: create_backup(root), 'lock')
        check(True, 'reject snapshot while manager lock held')
        expect_error(lambda: restore_backup(root, backup['name'], confirmation='NO'), 'RESTORE')
        check(True, 'restore requires explicit confirmation')
        # A replaced/modified ZIP payload fails integrity verification.
        altered = root / 'backups' / 'fastkv-backup-20260101-000000-aaaaaaaa.zip'
        with zipfile.ZipFile(archive) as inp, zipfile.ZipFile(altered, 'w') as out:
            for info in inp.infolist():
                content = inp.read(info.filename)
                if info.filename == 'cluster-data/node-1/data/appendonly.log': content += b'X'
                out.writestr(info.filename, content)
        expect_error(lambda: verify_archive(altered), 'size')
        check(True, 'detect modified backup content')
        traversal = root / 'backups' / 'fastkv-backup-20260101-000000-bbbbbbbb.zip'
        with zipfile.ZipFile(traversal, 'w') as out:
            out.writestr('../escape', 'x')
            out.writestr('manifest.json', '{}')
        expect_error(lambda: verify_archive(traversal), 'unsafe')
        check(True, 'reject ZIP traversal paths')
        # Safe snapshot restoration must not overwrite the old state irreversibly.
        (root / 'cluster-data/node-1/data/appendonly.log').write_bytes(b'SET favorite CHANGED\n')
        (root / 'dashboard/.last_config.json').write_text('{"capacity":8888}\n')
        result = restore_backup(root, backup['name'], confirmation='RESTORE')
        check((root / 'cluster-data/node-1/data/appendonly.log').read_bytes() == original,
              'restored original value')
        check((root / 'backups' / result['previous_data'] / 'node-1/data/appendonly.log').read_bytes() == b'SET favorite CHANGED\n',
              'previous cluster-data retained for rollback')
        check('4096' in (root / 'dashboard/.last_config.json').read_text() and
              '8888' in (root / 'backups' / result['previous_config']).read_text(),
              'dashboard config restored; previous config preserved')
        # Test dashboard API as a user would access it.
        ctrl = Controller(root=root)
        server = ThreadingHTTPServer((HOST, 0), Handler)
        server.controller = ctrl
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        port = server.server_port
        try:
            st, token = request(port, 'GET', '/api/session')
            csrf = token['csrf']
            st, listing = request(port, 'GET', '/api/backups')
            check(st == 200 and any(x['name'] == backup['name'] for x in listing['items']), 'dashboard lists archives')
            st, _ = request(port, 'POST', '/api/backup/create', {})
            check(st == 403, 'dashboard blocks backup mutation without CSRF')
            st, response = request(port, 'POST', '/api/backup/verify', {'name':backup['name']}, csrf)
            check(st == 200 and response['data']['verified'], 'dashboard archive verification')
            st, response = request(port, 'POST', '/api/backup/create', {}, csrf)
            check(st == 200 and response['data']['name'] != backup['name'], 'dashboard creates verified backup')
            st, response = request(port, 'POST', '/api/backup/restore', {'name': backup['name'], 'confirmation':'NO'}, csrf)
            check(st == 409, 'dashboard rejects restore without RESTORE')
        finally:
            server.shutdown();server.server_close();thread.join(timeout=3)


def wire(message):
    with socket.create_connection(('127.0.0.1', 7001), timeout=3) as sock:
        sock.settimeout(3)
        sock.sendall((message + '\n').encode())
        data = bytearray()
        while b'\n' not in data:
            chunk = sock.recv(4096)
            if not chunk: break
            data.extend(chunk)
        return data.decode().strip()


def wait_ready():
    deadline=time.monotonic()+8
    while time.monotonic()<deadline:
        try:
            if wire('PING')=='PONG': return
        except OSError:
            time.sleep(.12)
    raise AssertionError('Router did not start')


def start(root, manager, node):
    p=subprocess.Popen([str(manager),str(node),'60','4096','2','1'],cwd=root,
                       stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
    wait_ready()
    return p


def stop(p):
    p.terminate()
    try: p.wait(timeout=8)
    except subprocess.TimeoutExpired:
        p.kill();p.wait(timeout=5)
    deadline=time.monotonic()+5
    while time.monotonic()<deadline:
        try:
            with socket.create_connection(('127.0.0.1',7001),timeout=.1):
                time.sleep(.1)
        except OSError:
            return
    raise AssertionError('Router still running after manager termination')


def live_test(manager: Path, node: Path):
    for port in [7001,6381,7381]:
        with socket.socket() as sk:
            if sk.connect_ex(('127.0.0.1', port)) == 0:
                raise SystemExit(f'Port {port} busy — stop dashboard cluster before Phase 10 test')
    with tempfile.TemporaryDirectory(prefix='fastkv-backup-live-') as t:
        root=Path(t)
        (root/'dashboard').mkdir()
        p=start(root,manager,node)
        try:
            assert wire('SET preserved HelloBackup') == 'OK'
            assert wire('SET expkey ttlvalue') == 'OK'
            assert wire('EXPIRE expkey 120') == '1'
            expect_error(lambda: create_backup(root), 'lock')
            check(True, 'live cluster backup refused safely')
        finally: stop(p)
        orig = create_backup(root)
        check(verify_archive(archive_path(root, orig['name']))['verified'], 'real C++ cluster backup verified')
        p=start(root,manager,node)
        try:
            assert wire('SET preserved REPLACED') == 'OK'
        finally: stop(p)
        res=restore_backup(root,orig['name'],confirmation='RESTORE')
        p=start(root,manager,node)
        try:
            check(wire('GET preserved')=='HelloBackup', 'restored key survives C++ manager restart')
            ttl=int(wire('TTL expkey'))
            check(0 < ttl <= 120, 'absolute TTL deadline recovered without reset')
            stat=wire('CLUSTER STATUS')
            check('replica_state=ready' in stat, 'replica seeds from restored primary data')
            assert (root/'backups'/res['previous_data']).exists()
        finally: stop(p)


if __name__ == '__main__':
    unit_and_dashboard()
    if len(sys.argv)==3:
        live_test(Path(sys.argv[1]).resolve(),Path(sys.argv[2]).resolve())
    else:
        print('No binary paths supplied: C++ live test skipped')
    print('ALL PHASE 10 BACKUP TESTS PASSED')
