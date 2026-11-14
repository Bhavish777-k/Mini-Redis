#!/usr/bin/env python3
"""Fast-KV cluster dashboard and lifecycle control plane.

Run from any directory with: python3 dashboard/app.py
The cluster manager and KV node binaries are built in <repo>/build-debug.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import secrets
import signal
import socket
import subprocess
import sys
import threading
import time
from collections import deque
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

try:
    from .backup_ops import BackupError, archive_path, create_backup, list_backups, restore_backup, verify_archive
except ImportError:  # launched as python dashboard/app.py
    from backup_ops import BackupError, archive_path, create_backup, list_backups, restore_backup, verify_archive

ROOT = Path(__file__).resolve().parent.parent
STATIC = Path(__file__).resolve().parent / "static"
HOST = "127.0.0.1"
DEFAULT_PORT = 8765
ROUTER_PORT = 7001
MAX_REQUEST_BYTES = 8192
VALID_KEY = re.compile(r"^[^\s\x00-\x1f\x7f]{1,120}$")
VALID_VALUE = re.compile(r"^[^\s\x00-\x1f\x7f]{1,2048}$")


class UserError(Exception):
    pass


def wire(command: str, *, port: int = ROUTER_PORT, timeout: float = 1.0) -> str:
    if '\n' in command or '\r' in command or '\x00' in command:
        raise UserError("Multiline commands are not supported")
    try:
        with socket.create_connection((HOST, port), timeout=timeout) as sock:
            sock.settimeout(timeout)
            sock.sendall((command + "\n").encode("utf-8"))
            result = bytearray()
            while b'\n' not in result:
                chunk = sock.recv(4096)
                if not chunk:
                    raise ConnectionError("Router closed the connection")
                result.extend(chunk)
                if len(result) > 128 * 1024:
                    raise ConnectionError("Router response too long")
            return bytes(result).split(b'\n', 1)[0].decode("utf-8", errors="replace").rstrip('\r')
    except (OSError, UnicodeError) as exc:
        raise ConnectionError(f"Fast-KV router unavailable: {exc}") from exc


def parse_stats(raw: str) -> dict:
    """Parse the manager's existing flattened CLUSTER STATUS wire response."""
    words = raw.split()
    if len(words) < 2 or not words[0].startswith('nodes='):
        raise ValueError("Unknown CLUSTER STATUS reply: " + raw[:200])
    try:
        count = int(words[0].split('=', 1)[1])
        max_nodes = int(words[1].split('=', 1)[1])
        if not (0 <= count <= 32 and 1 <= max_nodes <= 32):
            raise ValueError("Invalid node count")
        nodes = []
        i = 2
        while i < len(words):
            token = words[i]
            if not token.startswith('port='):
                raise ValueError(f"Unexpected token: {token}")
            node = {"port": int(token.split('=', 1)[1])}
            i += 1
            usage = words[i]; i += 1
            if usage == 'unavailable':
                node.update(used=None, capacity=None, online=False)
            else:
                used, capacity = usage.split('/')
                node.update(used=int(used), capacity=int(capacity), online=True)
            while i < len(words) and not words[i].startswith('port='):
                part = words[i]
                if '=' in part:
                    key, val = part.split('=', 1)
                    if key in ('pid', 'restarts', 'replica', 'replica_pid', 'promotions'):
                        node[key] = int(val)
                    elif key == 'replica_usage':
                        if val == 'unavailable':
                            node['replica_used'] = None
                            node['replica_capacity'] = None
                        else:
                            a, b = val.split('/')
                            node['replica_used'] = int(a)
                            node['replica_capacity'] = int(b)
                    else:
                        node[key] = val
                i += 1
            nodes.append(node)
        if len(nodes) != count:
            raise ValueError("Node count mismatch")
    except (ValueError, IndexError, TypeError) as exc:
        raise ValueError("Could not parse manager status: " + raw[:200]) from exc
    return {"nodes": nodes, "node_count": count, "max_nodes": max_nodes,
            "replication": bool(nodes and 'replica' in nodes[0])}


def parse_os_stats(raw: str) -> dict[int, dict]:
    """Parse OSSTATS into a map keyed by primary/replica TCP port."""
    result = {}
    for segment in raw.split(' | '):
        fields = {}
        for part in segment.split():
            if '=' in part:
                key, value = part.split('=', 1)
                fields[key] = value
        port_str = fields.get('node', fields.get('replica'))
        try:
            port = int(port_str)
        except (TypeError, ValueError):
            continue
        result[port] = {
            'rss_bytes': int(fields['rss_bytes']) if fields.get('rss_bytes', '').isdigit() else None,
            'nofile_limit': fields.get('nofile_soft_limit', 'unknown'),
            'os_memory_enforced': fields.get('os_memory_enforced', 'no') == 'yes',
        }
    return result


def parse_metrics(raw: str) -> dict:
    """Parse the single-line METRICS router response. No floating-point NaN/Inf."""
    import math
    fields = {}
    for token in raw.split():
        if '=' not in token:
            raise ValueError('Malformed METRICS response')
        name, value = token.split('=', 1)
        fields[name] = value
    integer_names = ('uptime_s', 'requests_total', 'requests_ok', 'requests_err',
                     'recent_requests', 'recent_errors', 'p95_us_le', 'get_count', 'set_count')
    float_names = ('rps_10s', 'error_rate_10s_pct', 'avg_us', 'get_avg_us', 'set_avg_us')
    if set(fields) != set(integer_names) | set(float_names):
        raise ValueError('METRICS schema mismatch')
    parsed = {name: int(fields[name]) for name in integer_names}
    parsed.update({name: float(fields[name]) for name in float_names})
    if any(value < 0 or not math.isfinite(value) for value in parsed.values()):
        raise ValueError('Invalid METRICS values')
    if parsed['requests_ok'] + parsed['requests_err'] != parsed['requests_total']:
        raise ValueError('Inconsistent METRICS counters')
    return parsed


class Controller:
    def __init__(self, root: Path = ROOT, router_port: int = ROUTER_PORT):
        self.root = Path(root)
        self.router_port = router_port
        self.lock = threading.RLock()
        self.process: subprocess.Popen | None = None
        self.log_path = self.root / "dashboard" / ".manager.log"
        self.log_handle = None
        self.config_path = self.root / "dashboard" / ".last_config.json"
        self.token = secrets.token_urlsafe(32)
        self.events = deque(maxlen=80)
        self.events.append({"time": time.strftime('%H:%M:%S'), "message": "Dashboard ready"})

    def _event(self, message):
        self.events.appendleft({"time": time.strftime('%H:%M:%S'), "message": message})

    def settings(self):
        defaults = {"threshold": 60, "capacity": 4096, "max_nodes": 3, "replicas": 1}
        try:
            data = json.loads(self.config_path.read_text())
            if all(isinstance(data.get(k), int) for k in defaults):
                defaults.update({k: data[k] for k in defaults})
        except (OSError, ValueError):
            pass
        return defaults

    @staticmethod
    def validate_settings(obj):
        if not isinstance(obj, dict):
            raise UserError("Configuration must be an object")
        expected = (('threshold', 1, 99), ('capacity', 256, 1_073_741_824),
                    ('max_nodes', 1, 32), ('replicas', 0, 1))
        config = {}
        for key, low, high in expected:
            value = obj.get(key)
            if type(value) is not int or not low <= value <= high:
                raise UserError(f"{key} must be an integer in {low}–{high}")
            config[key] = value
        return config

    def binaries(self):
        manager = self.root / 'build-debug' / 'cluster-manager'
        storage = self.root / 'build-debug' / 'fast-kv'
        if not manager.is_file() or not storage.is_file():
            raise UserError("Build first: cmake -S . -B build-debug && cmake --build build-debug -j4")
        return manager.resolve(), storage.resolve()

    def ping(self):
        try:
            return wire('PING', port=self.router_port, timeout=0.3) == 'PONG'
        except ConnectionError:
            return False

    def start(self, payload):
        config = self.validate_settings(payload)
        with self.lock:
            if self.ping():
                raise UserError("A cluster already owns router port 7001. Attach to it instead of starting another.")
            if self.process and self.process.poll() is None:
                raise UserError("A manager is already starting")
            manager, storage = self.binaries()
            self.log_path.parent.mkdir(exist_ok=True)
            if self.log_handle:
                self.log_handle.close()
            self.log_handle = self.log_path.open('a', encoding='utf-8')
            args = [str(manager), str(storage), str(config['threshold']),
                    str(config['capacity']), str(config['max_nodes']), str(config['replicas'])]
            self.process = subprocess.Popen(args, cwd=str(self.root),
                                            stdout=self.log_handle, stderr=subprocess.STDOUT,
                                            stdin=subprocess.DEVNULL, close_fds=True)
            self._event(f"Starting cluster ({config['max_nodes']} max nodes, replicas={config['replicas']})")
            try:
                self.config_path.write_text(json.dumps(config, indent=2) + '\n')
            except OSError:
                pass
            deadline = time.monotonic() + 6
            while time.monotonic() < deadline:
                if self.ping():
                    self._event("Router online on 127.0.0.1:7001")
                    return self.status()
                if self.process.poll() is not None:
                    raise UserError("Manager failed to start. Open the manager logs for details.")
                time.sleep(0.1)
            raise UserError("Manager did not become ready. Check dashboard logs.")

    def stop(self):
        with self.lock:
            if not self.process or self.process.poll() is not None:
                raise UserError("Dashboard can stop only a manager launched by this dashboard")
            self.process.terminate()
            try:
                self.process.wait(timeout=6)
            except subprocess.TimeoutExpired:
                raise UserError("Manager did not stop gracefully; use your terminal to investigate")
            self._event("Managed cluster stopped")
            if self.log_handle:
                self.log_handle.close()
                self.log_handle = None
            return {"stopped": True}

    def resize(self, payload):
        if not isinstance(payload, dict):
            raise UserError("Invalid request")
        port, capacity = payload.get('port'), payload.get('capacity')
        if type(port) is not int or not (6381 <= port <= 6412 or 7381 <= port <= 7412):
            raise UserError("Select a valid storage node")
        if type(capacity) is not int or capacity <= 0 or capacity > 1_073_741_824:
            raise UserError("Capacity must be between 1 byte and 1 GiB")
        if not self.ping():
            raise UserError("Start or attach to a running cluster first")
        manager, _ = self.binaries()
        try:
            done = subprocess.run([str(manager), 'resize', str(port), str(capacity)],
                                  cwd=str(self.root), capture_output=True, text=True,
                                  timeout=6, check=False)
        except subprocess.TimeoutExpired:
            raise UserError("Resize timed out")
        if done.returncode:
            raise UserError((done.stderr or done.stdout or 'Resize rejected').strip()[:400])
        self._event(f"Resized node {port} to {capacity:,} bytes")
        return {"message": done.stdout.strip()}

    def data_command(self, payload):
        if not isinstance(payload, dict):
            raise UserError("Invalid request")
        action = payload.get('action')
        key = payload.get('key')
        if action not in ('GET', 'SET', 'DEL', 'WHERE', 'INCR') or not isinstance(key, str) or not VALID_KEY.fullmatch(key):
            raise UserError("Provide a valid key (1–120 characters, no spaces/control characters)")
        command = action + ' ' + key
        if action == 'SET':
            value = payload.get('value')
            if not isinstance(value, str) or not VALID_VALUE.fullmatch(value):
                raise UserError("Value must be 1–2,048 characters without whitespace")
            if value == '':
                raise UserError("Provide a non-empty value")
            command += ' ' + value
        if action == 'SET':
            # Same lifetime policy as SDK and CLI. A missing mode inherits
            # the database default. Explicit permanent is not the same thing.
            suffix = self._lifetime_suffix(payload)
            command += suffix
        response = wire(command, port=self.router_port)
        if response.startswith('ERR'):
            raise UserError(response)
        self._event(f"{action} {key}")
        return {"reply": response}

    @staticmethod
    def _lifetime_suffix(payload):
        mode = payload.get('ttl_mode', 'default')
        if mode == 'default': return ''
        if mode == 'never': return ' PERSIST'
        if mode == 'keep': return ' KEEPTTL'
        if mode == 'seconds':
            seconds = payload.get('ttl_seconds')
            if type(seconds) is not int or not 1 <= seconds <= 3153600000:
                raise UserError('TTL must be an integer between 1 and 3153600000 seconds')
            return ' EX ' + str(seconds)
        raise UserError('Choose Database default, Keep existing, Never or custom TTL')

    def ttl_policy(self, payload):
        if not isinstance(payload, dict): raise UserError('Invalid TTL policy')
        mode = payload.get('mode')
        if mode == 'never': requested = 'never'
        elif mode == 'seconds':
            seconds = payload.get('seconds')
            if type(seconds) is not int or not 1 <= seconds <= 3153600000:
                raise UserError('Database default TTL must be 1..3153600000 seconds')
            requested = str(seconds)
        else: raise UserError('Choose Never expire or seconds')
        answer = wire('TTLDEFAULT SET ' + requested, port=self.router_port)
        if answer != 'OK': raise UserError(answer)
        self._event('Updated developer default TTL to ' + requested)
        return {'default_ttl': None if requested == 'never' else int(requested)}

    # Phase 11: a bounded key browser; all operations go through the router.
    @staticmethod
    def _browser_key(payload):
        key = payload.get('key') if isinstance(payload, dict) else None
        if not isinstance(key, str) or not VALID_KEY.fullmatch(key) or len(key.encode('utf-8')) > 120:
            raise UserError('Key must be 1–120 UTF-8 bytes without whitespace/control characters')
        return key

    @staticmethod
    def _browser_ttl(payload):
        mode = payload.get('ttl_mode')
        if mode in ('default', 'never', 'keep'):
            return None
        if mode != 'seconds':
            raise UserError('Choose default, keep, never or a positive TTL')
        seconds = payload.get('ttl_seconds')
        if type(seconds) is not int or not 1 <= seconds <= 3153600000:
            raise UserError('TTL must be an integer between 1 and 3153600000 seconds')
        return seconds

    def browser_scan(self, payload):
        if not isinstance(payload, dict):
            raise UserError('Invalid scan request')
        limit = payload.get('limit', 20)
        cursor = payload.get('cursor', '-')
        prefix = payload.get('prefix', '')
        if type(limit) is not int or not 1 <= limit <= 50:
            raise UserError('Page size must be between 1 and 50')
        if not isinstance(cursor, str) or (cursor != '-' and
            (not cursor or len(cursor) > 240 or len(cursor) % 2 or
             any(x not in '0123456789abcdefABCDEF' for x in cursor))):
            raise UserError('Invalid cursor')
        if not isinstance(prefix, str) or (prefix and (not VALID_KEY.fullmatch(prefix) or
            len(prefix.encode('utf-8')) > 120)):
            raise UserError('Invalid prefix')
        answer = wire('SCAN {} {} {}'.format(cursor, limit, prefix.encode('utf-8').hex() or '-'),
                      port=self.router_port, timeout=3)
        if answer.startswith('ERR'):
            raise UserError(answer)
        parts = answer.split(' ')
        if len(parts) < 2 or not parts[0].startswith('next=') or not parts[1].startswith('count='):
            raise UserError('Invalid SCAN response')
        next_cursor = parts[0][5:]
        try:
            count = int(parts[1][6:])
            rows = []
            for item in parts[2:]:
                if not item.startswith('key='): raise ValueError('Invalid key field')
                try:
                    key = bytes.fromhex(item[4:]).decode('utf-8')
                except UnicodeDecodeError:
                    continue  # Binary keys cannot be edited in the text-only browser.
                if not VALID_KEY.fullmatch(key) or len(key.encode('utf-8')) > 120: continue
                ttl = wire('TTL ' + key, port=self.router_port, timeout=2)
                if ttl == '-2': continue
                if not ttl.lstrip('-').isdigit(): raise ValueError('Invalid TTL')
                owner = wire('WHERE ' + key, port=self.router_port, timeout=2)
                if owner == '(nil)': continue
                rows.append({'key': key, 'ttl': int(ttl), 'owner': owner})
            if len(parts)-2 != count: raise ValueError('Invalid scan count')
        except (ValueError, UnicodeError) as exc:
            raise UserError('Invalid SCAN response') from exc
        return {'items': rows, 'next_cursor': next_cursor, 'limit': limit,
                'prefix': prefix, 'may_change': True}

    def browser_detail(self, payload):
        key = self._browser_key(payload)
        owner = wire('WHERE ' + key, port=self.router_port)
        if owner == '(nil)':
            return {'key': key, 'found': False}
        value = wire('GET ' + key, port=self.router_port)
        ttl = wire('TTL ' + key, port=self.router_port)
        if ttl == '-2': return {'key': key, 'found': False}
        if not ttl.lstrip('-').isdigit():
            raise UserError('Unable to read key safely')
        return {'key': key, 'found': True, 'value': value, 'ttl': int(ttl), 'owner': owner}

    def browser_save(self, payload):
        key = self._browser_key(payload)
        value = payload.get('value')
        if not isinstance(value, str) or not VALID_VALUE.fullmatch(value):
            raise UserError('Value must be 1–2048 characters without whitespace')
        ttl = self._browser_ttl(payload)
        overwrite = payload.get('overwrite', False)
        if type(overwrite) is not bool: raise UserError('Invalid overwrite flag')
        if not overwrite and wire('WHERE ' + key, port=self.router_port) != '(nil)':
            raise UserError('Key already exists. Open it to edit instead.')
        command = 'SET ' + key + ' ' + value + self._lifetime_suffix(payload)
        result = wire(command, port=self.router_port)
        if result != 'OK': raise UserError(result)
        self._event(('Updated' if overwrite else 'Created') + ' key ' + key)
        return {'key':key, 'saved':True, 'ttl_seconds':ttl,
                'lifetime_mode':payload.get('ttl_mode','default')}

    def browser_expire(self, payload):
        key = self._browser_key(payload)
        ttl = self._browser_ttl(payload)
        if wire('WHERE ' + key, port=self.router_port) == '(nil)':
            raise UserError('Key does not exist')
        mode = payload.get('ttl_mode')
        if mode == 'keep':
            return {'key': key, 'ttl_seconds': None, 'applied': False}
        if mode == 'default':
            setting = wire('TTLDEFAULT GET', port=self.router_port)
            if setting == 'never': ttl = None
            elif setting.isdigit(): ttl = int(setting)
            else: raise UserError('Unable to read default TTL policy')
        cmd = ('PERSIST ' + key) if ttl is None else ('EXPIRE ' + key + ' ' + str(ttl))
        result = wire(cmd, port=self.router_port)
        if result not in ('0', '1') or (ttl is not None and result != '1'):
            raise UserError(result)
        self._event('Changed expiration for ' + key)
        return {'key':key,'ttl_seconds':ttl,'applied':True}

    def browser_delete(self, payload):
        key = self._browser_key(payload)
        if payload.get('confirmation') != key:
            raise UserError('Confirm the exact key to delete')
        result = wire('DEL ' + key, port=self.router_port)
        if result not in ('0','1'): raise UserError(result)
        self._event('Deleted key ' + key)
        return {'key':key,'deleted':result == '1'}

    def backup_create(self):
        with self.lock:
            if self.process and self.process.poll() is None:
                raise UserError("Stop this dashboard's cluster before making an offline backup")
            result = create_backup(self.root)
            self._event(f"Created verified offline backup {result['name']}")
            return result

    def backup_verify(self, payload):
        name = payload.get('name') if isinstance(payload, dict) else None
        return verify_archive(archive_path(self.root, name))

    def backup_restore(self, payload):
        if not isinstance(payload, dict):
            raise UserError("Choose a backup and confirm restoration")
        with self.lock:
            if self.process and self.process.poll() is None:
                raise UserError("Stop this dashboard's cluster before restoring")
            result = restore_backup(self.root, payload.get('name'), confirmation=payload.get('confirmation'))
            self._event(f"Restored {result['name']}; previous data saved in backups/{result['previous_data']}")
            return result

    def recent_logs(self):
        try:
            # Keep it bounded: only inspect last 32 KiB; never expose arbitrary paths.
            with self.log_path.open('rb') as log:
                log.seek(0, os.SEEK_END)
                log.seek(max(0, log.tell() - 32768))
                data = log.read().decode('utf-8', errors='replace')
            return data.splitlines()[-45:]
        except OSError:
            return []

    def status(self):
        owned = bool(self.process and self.process.poll() is None)
        data = {"online": False, "owned": owned, "manager_pid": self.process.pid if owned else None,
                "node_count": 0, "max_nodes": self.settings()['max_nodes'],
                "replication": False, "nodes": [], "config": self.settings(),
                "metrics": None, "events": list(self.events)[:12]}
        try:
            raw = wire('CLUSTER STATUS', port=self.router_port, timeout=0.7)
            if raw.startswith('ERR'):
                raise ConnectionError(raw)
            parsed = parse_stats(raw)
            data.update(parsed)
            try:
                os_report = parse_os_stats(wire('OSSTATS', port=self.router_port, timeout=0.7))
                for node in parsed['nodes']:
                    node.update(os_report.get(node['port'], {}))
                    if 'replica' in node:
                        replica_report = os_report.get(node['replica'], {})
                        node['replica_rss_bytes'] = replica_report.get('rss_bytes')
            except ConnectionError:
                pass
            data['online'] = True
            data['total_used'] = sum(n['used'] or 0 for n in parsed['nodes'])
            data['total_capacity'] = sum(n['capacity'] or 0 for n in parsed['nodes'])
            data['total_promotions'] = sum(n.get('promotions', 0) for n in parsed['nodes'])
            data['total_restarts'] = sum(n.get('restarts', 0) for n in parsed['nodes'])
        except (ConnectionError, ValueError):
            pass
        if data["online"]:
            try:
                data["metrics"] = parse_metrics(wire("METRICS", port=self.router_port, timeout=0.7))
            except (ConnectionError, ValueError):
                data["metrics"] = None
            try:
                lifetime = wire('TTLDEFAULT GET', port=self.router_port, timeout=0.7)
                data['default_ttl'] = None if lifetime == 'never' else int(lifetime)
            except (ConnectionError, ValueError):
                data['default_ttl'] = None
            try:
                data["key_count"] = int(wire("COUNT", port=self.router_port, timeout=0.7))
            except (ConnectionError, ValueError):
                data["key_count"] = None
        return data

    def close(self):
        try:
            if self.process and self.process.poll() is None:
                self.stop()
        except UserError:
            pass


class Handler(BaseHTTPRequestHandler):
    server_version = "FastKV-Dashboard/0.1"

    @property
    def control(self) -> Controller:
        return self.server.controller

    def _headers(self, code, kind, length):
        self.send_response(code)
        self.send_header('Content-Type', kind)
        self.send_header('Content-Length', str(length))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('X-Frame-Options', 'DENY')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.send_header('Content-Security-Policy',
                         "default-src 'self'; style-src 'self'; script-src 'self'; connect-src 'self'; object-src 'none'; frame-ancestors 'none'")
        self.end_headers()

    def _send(self, code, body, kind):
        self._headers(code, kind, len(body))
        self.wfile.write(body)

    def json(self, code, data):
        self._send(code, json.dumps(data, separators=(',', ':')).encode(), 'application/json; charset=utf-8')

    def _valid_host(self):
        actual = self.headers.get('Host', '')
        return actual in (f'127.0.0.1:{self.server.server_port}', f'localhost:{self.server.server_port}')

    def do_GET(self):
        if not self._valid_host():
            return self.json(403, {"error": "Localhost only"})
        path = urlsplit(self.path).path
        if path == '/api/status':
            return self.json(200, self.control.status())
        if path == '/api/logs':
            return self.json(200, {"lines": self.control.recent_logs()})
        if path == '/api/backups':
            try:
                return self.json(200, {'items': list_backups(self.control.root)})
            except BackupError as exc:
                return self.json(409, {'error': str(exc)})
        if path == '/api/session':
            return self.json(200, {"csrf": self.control.token})
        if path in ('/', '/index.html'):
            path = '/index.html'
        if path not in ('/index.html', '/app.js', '/styles.css'):
            return self.json(404, {"error": "Not found"})
        file = STATIC / path.lstrip('/')
        kind = 'text/html; charset=utf-8' if path.endswith('.html') else ('text/javascript; charset=utf-8' if path.endswith('.js') else 'text/css; charset=utf-8')
        try:
            return self._send(200, file.read_bytes(), kind)
        except OSError:
            return self.json(404, {"error": "Asset missing"})

    def do_POST(self):
        if not self._valid_host():
            return self.json(403, {"error": "Localhost only"})
        if self.headers.get('X-CSRF-Token') != self.control.token:
            return self.json(403, {"error": "Invalid request token"})
        origin = self.headers.get('Origin')
        if origin not in (None, f'http://127.0.0.1:{self.server.server_port}',
                         f'http://localhost:{self.server.server_port}'):
            return self.json(403, {"error": "Cross-origin requests are blocked"})
        try:
            size = int(self.headers.get('Content-Length', '0'))
            if size <= 0 or size > MAX_REQUEST_BYTES:
                raise UserError("Invalid request size")
            payload = json.loads(self.rfile.read(size))
            if self.path == '/api/start':
                result = self.control.start(payload)
            elif self.path == '/api/stop':
                result = self.control.stop()
            elif self.path == '/api/resize':
                result = self.control.resize(payload)
            elif self.path == '/api/key':
                result = self.control.data_command(payload)
            elif self.path == '/api/ttl-policy':
                result = self.control.ttl_policy(payload)
            elif self.path == '/api/keys/scan':
                result = self.control.browser_scan(payload)
            elif self.path == '/api/keys/detail':
                result = self.control.browser_detail(payload)
            elif self.path == '/api/keys/save':
                result = self.control.browser_save(payload)
            elif self.path == '/api/keys/expire':
                result = self.control.browser_expire(payload)
            elif self.path == '/api/keys/delete':
                result = self.control.browser_delete(payload)
            elif self.path == '/api/backup/create':
                result = self.control.backup_create()
            elif self.path == '/api/backup/verify':
                result = self.control.backup_verify(payload)
            elif self.path == '/api/backup/restore':
                result = self.control.backup_restore(payload)
            else:
                return self.json(404, {"error": "Unknown endpoint"})
            return self.json(200, {"ok": True, "data": result})
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            return self.json(400, {"error": f"Invalid input: {exc}"})
        except (UserError, ConnectionError, BackupError) as exc:
            return self.json(409, {"error": str(exc)})
        except OSError as exc:
            return self.json(500, {"error": f"OS operation failed: {exc}"})

    def log_message(self, fmt, *args):
        # Do not spam stdout with polling traffic.
        pass


def serve(port: int = DEFAULT_PORT, root: Path = ROOT):
    if not 1024 <= port <= 65535:
        raise ValueError('Port must be between 1024 and 65535')
    controller = Controller(root)
    server = ThreadingHTTPServer((HOST, port), Handler)
    server.controller = controller
    server.daemon_threads = True
    print(f'Fast-KV Dashboard: http://127.0.0.1:{port}', flush=True)
    try:
        server.serve_forever(poll_interval=0.15)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        controller.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Fast-KV local cluster dashboard')
    parser.add_argument('--port', type=int, default=DEFAULT_PORT)
    options = parser.parse_args()
    serve(options.port)
