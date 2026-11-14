#!/usr/bin/env python3
"""Tests launcher safety and real local start/stop. Requires no external packages.

Run as: python3 tests/test_easy_install.py ./build-debug/cluster-manager ./build-debug/fast-kv
Stop the main Fast-KV dashboard and cluster before running the integration test.
"""
from __future__ import annotations

import importlib.machinery
import importlib.util
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parent.parent
TEST_BINARIES = []


def load_launcher():
    loader = importlib.machinery.SourceFileLoader('fastkv_easy_installer', str(ROOT / 'bin/fastkv'))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


def tcp(port):
    try:
        with socket.create_connection(('127.0.0.1', port), timeout=0.3):
            return True
    except OSError:
        return False


def router(command):
    with socket.create_connection(('127.0.0.1', 7001), timeout=3) as s:
        s.settimeout(3)
        s.sendall((command + '\n').encode())
        buf = b''
        while b'\n' not in buf:
            b = s.recv(8192)
            if not b:
                raise RuntimeError('Router closed early')
            buf += b
        return buf.split(b'\n')[0].decode().rstrip('\r')


class UnitTests(unittest.TestCase):
    def test_new_cluster_defaults(self):
        mod = load_launcher()
        with tempfile.TemporaryDirectory() as d:
            orig = mod.ROOT
            mod.ROOT = Path(d)
            mod.DASHBOARD = Path(d) / 'dashboard'
            try:
                opts = type('Options', (), dict(capacity_mb=None, capacity_bytes=None,
                                                 threshold=None, max_nodes=None, replicas=None))()
                self.assertEqual(mod.requested_config(opts, None)['capacity'], 64*1024*1024)
                (mod.ROOT / 'cluster-data').mkdir()
                self.assertEqual(mod.requested_config(opts, None)['capacity'], 4096)
                (mod.ROOT / 'dashboard').mkdir()
                (mod.DASHBOARD / '.last_config.json').write_text(json.dumps({
                    'capacity': 123456, 'threshold': 70, 'max_nodes': 3, 'replicas': 1}))
                self.assertEqual(mod.requested_config(opts, None)['capacity'], 123456)
                opts.capacity_mb = 32
                self.assertEqual(mod.requested_config(opts, None)['capacity'], 33554432)
            finally:
                mod.ROOT = orig
                mod.DASHBOARD = orig / 'dashboard'

    def test_no_overwrite_invalid_config(self):
        mod = load_launcher()
        with tempfile.TemporaryDirectory() as d:
            orig = mod.ROOT
            mod.ROOT = Path(d)
            mod.DASHBOARD = Path(d) / 'dashboard'
            try:
                opts = type('Options', (), dict(capacity_mb=0, capacity_bytes=None,
                                                 threshold=None, max_nodes=None, replicas=None))()
                with self.assertRaises(mod.LauncherError):
                    mod.requested_config(opts, None)
                opts.capacity_mb = 128
                opts.replicas = 2
                with self.assertRaises(mod.LauncherError):
                    mod.requested_config(opts, None)
            finally:
                mod.ROOT = orig
                mod.DASHBOARD = orig / 'dashboard'


class IntegrationTests(unittest.TestCase):
    def test_real_cpp_cluster(self):
        if len(TEST_BINARIES) != 2:
            self.skipTest('Provide manager and storage paths for real cluster test')
        manager, storage = TEST_BINARIES
        if not manager.is_file() or not storage.is_file():
            self.skipTest('C++ executables not built')
        if tcp(8765) or tcp(7001) or tcp(6381) or tcp(7381):
            self.skipTest('Local Fast-KV port is busy; stop dashboard and cluster first')
        with tempfile.TemporaryDirectory(prefix='fastkv-final-easy-') as tmp:
            root = Path(tmp)
            (root/'dashboard').mkdir()
            (root/'dashboard/static').mkdir()
            for filename in ('app.py', 'backup_ops.py'):
                shutil.copy2(ROOT/'dashboard'/filename, root/'dashboard'/filename)
            for file in (ROOT/'dashboard/static').iterdir():
                if file.is_file():
                    shutil.copy2(file, root/'dashboard/static'/file.name)
            (root/'bin').mkdir()
            shutil.copy2(ROOT/'bin/fastkv', root/'bin/fastkv')
            (root/'build-debug').mkdir()
            shutil.copy2(manager, root/'build-debug/cluster-manager')
            shutil.copy2(storage, root/'build-debug/fast-kv')
            cli = root / 'bin/fastkv'
            def call(*argv, check=True):
                result = subprocess.run([sys.executable, str(cli), *argv], text=True,
                                        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                        timeout=22, check=False)
                if check and result.returncode:
                    raise AssertionError(f'{argv}: {result.returncode}\n{result.stdout}\n{result.stderr}')
                return result
            try:
                print('Starting real C++ cluster using fastkv start', flush=True)
                result = call('start', '--capacity-bytes', '4096', '--threshold', '60',
                              '--max-nodes', '2', '--replicas', '1')
                self.assertIn('Fast-KV started', result.stdout)
                self.assertEqual(router('PING'), 'PONG')
                self.assertEqual(router('SET final_demo hello'), 'OK')
                self.assertEqual(router('GET final_demo'), 'hello')
                self.assertIn('Cluster running', call('status').stdout)
                self.assertEqual(call('start').returncode, 0)
                self.assertTrue((root/'dashboard/.last_config.json').is_file())
                self.assertEqual(call('stop').returncode, 0)
                self.assertFalse(tcp(7001))
                self.assertIn('Cluster stopped', call('status').stdout)
                self.assertIn('Fast-KV started', call('start').stdout)
                self.assertEqual(router('GET final_demo'), 'hello')
                self.assertEqual(call('shutdown').returncode, 0)
                deadline = time.monotonic() + 5
                while time.monotonic() < deadline and tcp(8765):
                    time.sleep(0.1)
                self.assertFalse(tcp(8765))
                print('PASS: launcher start/stop/status/restart, restored data, dashboard shutdown', flush=True)
            finally:
                if tcp(8765):
                    call('shutdown', check=False)


if __name__ == '__main__':
    TEST_BINARIES = [Path(x).resolve() for x in sys.argv[1:3]]
    sys.argv[:] = [sys.argv[0]]
    unittest.main(verbosity=2)
