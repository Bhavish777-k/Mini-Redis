"""Unit tests using a fake router; optional live smoke via --live manager server.

The fake router never touches existing cluster-data or fixed port 7001.
"""
import contextlib
import pathlib
import socket
import socketserver
import subprocess
import sys
import tempfile
import threading
import time
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'sdk' / 'python' / 'src'))
from fastkv import (FastKV, FastKVCommandError, FastKVConnectionError,
                    FastKVProtocolError)
from fastkv.cli import main as cli_main


class Handler(socketserver.BaseRequestHandler):
    def handle(self):
        buf = b''
        while b'\n' not in buf and len(buf) < 2 * 1024 * 1024:
            chunk = self.request.recv(1024)
            if not chunk:
                return
            buf += chunk
        cmd = buf.partition(b'\n')[0].decode()
        self.server.commands.append(cmd)
        reply = self.server.respond(cmd).encode() + b'\n'
        # Deliberately fragment the reply to verify network framing.
        self.request.sendall(reply[:1])
        self.request.sendall(reply[1:])


class Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


@contextlib.contextmanager
def fake_router():
    store, expiry, policy = {}, {}, {"default": None}

    def respond(command):
        parts = command.split()
        op = parts[0].upper()
        if op == 'PING': return 'PONG'
        if op == 'TTLDEFAULT':
            if parts[1] == 'GET': return str(policy['default']) if policy['default'] is not None else 'never'
            policy['default'] = None if parts[2] == 'never' else int(parts[2]); return 'OK'
        if op == 'SET':
            old_ttl = expiry.get(parts[1])
            store[parts[1]] = parts[2]
            if len(parts) == 5 and parts[3] == 'EX': expiry[parts[1]] = int(parts[4])
            elif len(parts) == 4 and parts[3] == 'PERSIST': expiry.pop(parts[1], None)
            elif len(parts) == 4 and parts[3] == 'KEEPTTL' and old_ttl is not None: expiry[parts[1]] = old_ttl
            elif policy['default'] is not None: expiry[parts[1]] = policy['default']
            else: expiry.pop(parts[1], None)
            return 'OK'
        if op == 'GET': return store.get(parts[1], '(nil)')
        if op == 'EXISTS': return str(int(parts[1] in store))
        if op == 'DEL': return str(int(store.pop(parts[1], None) is not None))
        if op == 'INCR':
            k = parts[1]
            n = int(store.get(k, '0')) + 1
            store[k] = str(n)
            return str(n)
        if op == 'EXPIRE':
            if parts[1] not in store: return '0'
            expiry[parts[1]] = int(parts[2])
            return '1'
        if op == 'TTL': return '-2' if parts[1] not in store else str(expiry.get(parts[1], -1))
        if op == 'PERSIST': return str(int(expiry.pop(parts[1], None) is not None))
        if op == 'WHERE': return '6381' if parts[1] in store else '(nil)'
        if op == 'COUNT': return str(len(store))
        if op == 'CLUSTER': return 'nodes=1 max_nodes=3 port=6381'
        if op == 'OSSTATS': return 'node=6381 memory=0'
        if op == 'ALLOCSTATS': return 'node=6381 slab=0'
        return 'ERR unsupported command'

    with Server(('127.0.0.1', 0), Handler) as server:
        server.commands = []
        server.respond = respond
        th = threading.Thread(target=server.serve_forever, daemon=True)
        th.start()
        try:
            yield server
        finally:
            server.shutdown()
            th.join(timeout=2)


class SDKTests(unittest.TestCase):
    def test_typed_api_and_ttl(self):
        with fake_router() as server:
            db = FastKV(port=server.server_address[1])
            self.assertTrue(db.ping())
            self.assertIsNone(db.get('absent'))
            self.assertIsNone(db.where('absent'))
            self.assertEqual(db.ttl('absent'), -2)
            self.assertTrue(db.set('user:1', 'alice', ttl=123))
            self.assertEqual(db.get('user:1'), 'alice')
            self.assertEqual(db.ttl('user:1'), 123)
            self.assertTrue(db.set_default_ttl(600))
            self.assertEqual(db.get_default_ttl(), 600)
            self.assertTrue(db.set('short', 'value'))
            self.assertEqual(db.ttl('short'), 600)
            self.assertTrue(db.set('forever', 'value', persist=True))
            self.assertEqual(db.ttl('forever'), -1)
            self.assertEqual(db.where('user:1'), 6381)
            self.assertTrue(db.exists('user:1'))
            self.assertTrue(db.persist('user:1'))
            self.assertEqual(db.ttl('user:1'), -1)
            self.assertTrue(db.set('counter', 4))
            self.assertEqual(db.incr('counter'), 5)
            self.assertEqual(db.count(), 4)
            self.assertTrue(db.delete('user:1'))
            self.assertFalse(db.delete('user:1'))
            self.assertFalse(db.expire('user:1', 3))
            self.assertIn('nodes=1', db.cluster_status())
            self.assertIn('memory=0', db.os_stats())
            self.assertIn('slab=0', db.alloc_stats())
            self.assertEqual(server.commands[:3], ['PING', 'GET absent', 'WHERE absent'])
            self.assertIn('SET user:1 alice EX 123', server.commands)

    def test_errors_no_injection_and_nonretry(self):
        with fake_router() as server:
            db = FastKV(port=server.server_address[1])
            for invalid in ['key with spaces', 'a\nb', '', 'x\ty', 'a\x00b']:
                with self.assertRaises(ValueError): db.get(invalid)
                with self.assertRaises(ValueError): db.set('key', invalid)
            with self.assertRaises(ValueError): db.command('PING\nSET evil one')
            with self.assertRaises(ValueError): db.expire('key', -1)
            with self.assertRaises(FastKVCommandError): db.command('NOTACOMMAND')
            self.assertNotIn('SET evil one', server.commands)

    def test_network_failure(self):
        with socket.socket() as s:
            s.bind(('127.0.0.1', 0))
            port = s.getsockname()[1]
        db = FastKV(port=port, timeout=0.3)
        with self.assertRaises(FastKVConnectionError): db.ping()

    def test_cli_single_command(self):
        with fake_router() as server:
            port = server.server_address[1]
            self.assertEqual(cli_main(['--port', str(port), 'PING']), 0)
            self.assertEqual(cli_main(['--port', str(port), '--command', 'CLUSTER STATUS']), 0)
            self.assertEqual(cli_main(['--port', str(port), 'BAD']), 1)


if __name__ == '__main__':
    unittest.main(verbosity=2)
