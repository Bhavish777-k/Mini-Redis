"""Offline, checksum-verified Fast-KV cluster backups (standard library only).

Safety model: requires the manager/router/storage nodes to be stopped; holds the
manager's file lock while archiving or swapping directories. Restores always
retain the previous cluster-data directory for manual rollback. No hot snapshots.
"""
from __future__ import annotations

import contextlib
import datetime as dt
import fcntl
import hashlib
import json
import os
import re
import secrets
import shutil
import socket
import stat
import tempfile
import zipfile
from pathlib import Path, PurePosixPath

SCHEMA = 1
NAME = re.compile(r'^fastkv-backup-\d{8}-\d{6}-[a-f0-9]{8}\.zip$')
MAX_FILES = 10000
MAX_BYTES = 16 * 1024 ** 3
READ_SIZE = 1024 * 1024


class BackupError(Exception):
    """Expected validation/safety failure."""


def _utc_stamp() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime('%Y%m%d-%H%M%S')


def _port_list(root: Path):
    ports = [7001]
    store = root / 'cluster-data'
    if store.is_dir():
        for child in store.iterdir():
            match = re.fullmatch(r'(node|replica)-(\d{1,2})', child.name)
            if match:
                n = int(match[2])
                if 1 <= n <= 32:
                    ports.append((6380 if match[1] == 'node' else 7380) + n)
    return sorted(set(ports))


def _check_ports(root: Path):
    for port in _port_list(root):
        try:
            with socket.create_connection(('127.0.0.1', port), timeout=0.06):
                raise BackupError(f'TCP port {port} is active. Stop the cluster before creating/restoring a backup.')
        except (ConnectionRefusedError, TimeoutError, OSError):
            continue


@contextlib.contextmanager
def offline_lock(root: Path, *, allow_missing: bool = False):
    """Cooperate with the C++ manager's flock on cluster-data/manager.lock."""
    data = root / 'cluster-data'
    if allow_missing and not data.exists():
        data.mkdir(mode=0o700)
    if not data.is_dir() or data.is_symlink():
        raise BackupError('cluster-data directory is missing or is a symlink')
    lockpath = data / 'manager.lock'
    if lockpath.is_symlink():
        raise BackupError('Manager lock must not be a symlink')
    fd = os.open(lockpath, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise BackupError('Cluster manager lock is held. Stop the cluster first.') from exc
        _check_ports(root)
        yield
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def _safe_path(name: str):
    if not isinstance(name, str) or not name or '\\' in name or '\x00' in name:
        raise BackupError('Invalid archive entry path')
    p = PurePosixPath(name)
    if p.is_absolute() or any(x in ('', '.', '..') for x in name.split('/')) or p.as_posix() != name:
        raise BackupError('Unsafe path in archive')
    if not (name.startswith('cluster-data/') or name == 'dashboard/.last_config.json'):
        raise BackupError('Archive contains an unexpected path')
    if name == 'cluster-data/manager.lock' or name == 'cluster-data/resize.lock':
        raise BackupError('Runtime lock files must not be in backups')
    return p


def _files(root: Path):
    data = root / 'cluster-data'
    if not data.is_dir():
        raise BackupError('No cluster-data directory to back up')
    selected = []
    for current, dirs, files in os.walk(data, followlinks=False):
        folder = Path(current)
        for d in dirs:
            if (folder / d).is_symlink():
                raise BackupError('Refusing to archive a symlink directory')
        for item in files:
            path = folder / item
            rel = path.relative_to(root).as_posix()
            if rel in ('cluster-data/manager.lock', 'cluster-data/resize.lock'):
                continue
            if path.is_symlink() or not path.is_file():
                raise BackupError(f'Refusing non-regular file: {rel}')
            if path.name.endswith(('.tmp', '.copying')) or path.name == 'pending_lifetime_write':
                raise BackupError(f'Incomplete storage operation detected: {rel}')
            _safe_path(rel)
            selected.append((rel, path))
    cfg = root / 'dashboard/.last_config.json'
    if cfg.exists():
        if cfg.is_symlink() or not cfg.is_file():
            raise BackupError('Invalid dashboard configuration path')
        selected.append(('dashboard/.last_config.json', cfg))
    if not selected or not any(n.startswith('cluster-data/') for n, _ in selected):
        raise BackupError('No persistent database files found')
    if len(selected) > MAX_FILES:
        raise BackupError('Too many database files')
    return sorted(selected)


def _digest_file(path: Path):
    h = hashlib.sha256()
    count = 0
    with path.open('rb') as f:
        while chunk := f.read(READ_SIZE):
            h.update(chunk)
            count += len(chunk)
    return count, h.hexdigest()


def _digest_stream(stream, limit):
    h = hashlib.sha256()
    count = 0
    while chunk := stream.read(READ_SIZE):
        h.update(chunk)
        count += len(chunk)
        if count > limit:
            raise BackupError('File larger than declared size')
    return count, h.hexdigest()


def create_backup(root: Path) -> dict:
    root = Path(root).resolve()
    with offline_lock(root):
        selected = _files(root)
        backup_dir = root / 'backups'
        backup_dir.mkdir(mode=0o700, exist_ok=True)
        if backup_dir.is_symlink():
            raise BackupError('Backup directory cannot be a symlink')
        name = f'fastkv-backup-{_utc_stamp()}-{secrets.token_hex(4)}.zip'
        out = backup_dir / name
        staging = backup_dir / f'.{name}.partial'
        entries = []
        total = 0
        try:
            with zipfile.ZipFile(staging, 'x', compression=zipfile.ZIP_DEFLATED, compresslevel=6, allowZip64=True) as z:
                for rel, path in selected:
                    length, digest = _digest_file(path)
                    total += length
                    if total > MAX_BYTES:
                        raise BackupError('Backup exceeds configured 16 GiB safety limit')
                    z.write(path, rel)
                    entries.append({'path': rel, 'size': length, 'sha256': digest})
                manifest = {
                    'format': 'fastkv-offline-backup', 'version': SCHEMA,
                    'created_utc': dt.datetime.now(dt.timezone.utc).isoformat(),
                    'files': entries,
                }
                z.writestr('manifest.json', json.dumps(manifest, indent=2) + '\n')
            verify_archive(staging)
            # Do not overwrite an existing archive, even on a name collision.
            try:
                os.link(staging, out)
            except FileExistsError as exc:
                raise BackupError('Backup name collision; retry creation') from exc
            os.chmod(out, 0o600)
        finally:
            staging.unlink(missing_ok=True)
    return {'name': name, 'files': len(entries), 'bytes': total, 'archive_bytes': out.stat().st_size}


def verify_archive(path: Path) -> dict:
    path = Path(path)
    if not path.is_file() or path.is_symlink():
        raise BackupError('Backup archive not found')
    try:
        with zipfile.ZipFile(path, 'r') as z:
            infos = z.infolist()
            if not (2 <= len(infos) <= MAX_FILES + 1):
                raise BackupError('Unexpected archive entry count')
            names = [info.filename for info in infos]
            if names.count('manifest.json') != 1 or len(set(names)) != len(names):
                raise BackupError('Missing/duplicate manifest or repeated file')
            for info in infos:
                if info.is_dir() or stat.S_IFMT(info.external_attr >> 16) == stat.S_IFLNK:
                    raise BackupError('No symlinks or directories allowed in backup archives')
                if info.filename != 'manifest.json':
                    _safe_path(info.filename)
            manifest_info = z.getinfo('manifest.json')
            if manifest_info.file_size > 2 * 1024 * 1024:
                raise BackupError('Manifest too large')
            manifest = json.loads(z.read('manifest.json'))
            if not isinstance(manifest, dict) or manifest.get('format') != 'fastkv-offline-backup' or manifest.get('version') != SCHEMA:
                raise BackupError('Unsupported backup format')
            entries = manifest.get('files')
            if not isinstance(entries, list) or len(entries) != len(infos) - 1:
                raise BackupError('Invalid backup manifest')
            seen = set()
            total = 0
            for record in entries:
                if not isinstance(record, dict) or set(record) != {'path', 'size', 'sha256'}:
                    raise BackupError('Invalid manifest file record')
                name, size, sha = record['path'], record['size'], record['sha256']
                _safe_path(name)
                if name in seen or name not in names or type(size) is not int or size < 0 or size > MAX_BYTES or not isinstance(sha, str) or not re.fullmatch(r'[a-f0-9]{64}', sha):
                    raise BackupError('Invalid manifest integrity metadata')
                seen.add(name)
                total += size
                if total > MAX_BYTES or z.getinfo(name).file_size != size:
                    raise BackupError('Archive size metadata inconsistent')
                with z.open(name, 'r') as stream:
                    actual_size, actual_sha = _digest_stream(stream, size)
                if actual_size != size or actual_sha != sha:
                    raise BackupError(f'Backup checksum mismatch: {name}')
            if set(names) != seen | {'manifest.json'}:
                raise BackupError('Unexpected entries in backup')
            if not any(name.startswith('cluster-data/') for name in seen):
                raise BackupError('Backup contains no database data')
            return {'files': len(entries), 'bytes': total, 'created_utc': manifest.get('created_utc'), 'verified': True}
    except (zipfile.BadZipFile, zipfile.LargeZipFile, EOFError, json.JSONDecodeError, UnicodeError, KeyError, OSError, ValueError, RuntimeError) as exc:
        raise BackupError(f'Corrupt or unreadable backup: {exc}') from exc


def archive_path(root: Path, name: str) -> Path:
    if not isinstance(name, str) or not NAME.fullmatch(name):
        raise BackupError('Choose a backup from the listed archive names')
    root = Path(root).resolve()
    path = root / 'backups' / name
    if not path.is_file() or path.is_symlink():
        raise BackupError('Backup archive not found')
    return path


def list_backups(root: Path) -> list[dict]:
    base = Path(root).resolve() / 'backups'
    if not base.exists():
        return []
    if not base.is_dir() or base.is_symlink():
        raise BackupError('Invalid backup directory')
    return sorted(({'name': p.name, 'archive_bytes': p.stat().st_size} for p in base.iterdir()
                   if NAME.fullmatch(p.name) and p.is_file() and not p.is_symlink()),
                  key=lambda item: item['name'], reverse=True)


def restore_backup(root: Path, name: str, *, confirmation: str) -> dict:
    if confirmation != 'RESTORE':
        raise BackupError('Restoration requires typing RESTORE to confirm')
    root = Path(root).resolve()
    archive = archive_path(root, name)
    with offline_lock(root, allow_missing=True):
        checked = verify_archive(archive)
        # Stage all restored files in a private temp directory on the same filesystem.
        with tempfile.TemporaryDirectory(prefix='.fastkv-restoring-', dir=root) as temp:
            stage = Path(temp)
            with zipfile.ZipFile(archive, 'r') as z:
                manifest = json.loads(z.read('manifest.json'))
                for record in manifest['files']:
                    rel = _safe_path(record['path'])
                    target = stage.joinpath(*rel.parts)
                    target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
                    with z.open(record['path']) as incoming, target.open('xb') as outgoing:
                        shutil.copyfileobj(incoming, outgoing, READ_SIZE)
                    os.chmod(target, 0o600)
            new_dir = stage / 'cluster-data'
            if not new_dir.is_dir():
                raise BackupError('Missing data directory in backup')
            # Hold the new manager.lock as well, so an external manager cannot
            # start halfway through the directory swap.
            new_fd = os.open(new_dir / 'manager.lock', os.O_RDWR | os.O_CREAT, 0o600)
            fcntl.flock(new_fd, fcntl.LOCK_EX)
            old_dir = root / 'cluster-data'
            preserved = root / 'backups' / f'cluster-data-before-restore-{_utc_stamp()}-{secrets.token_hex(4)}'
            original_config = root / 'dashboard/.last_config.json'
            restored_config = stage / 'dashboard/.last_config.json'
            backup_config = root / 'backups' / f'.last_config.before-restore-{_utc_stamp()}-{secrets.token_hex(4)}.json'
            moved_old = False
            moved_new = False
            saved_config = False
            try:
                os.rename(old_dir, preserved)
                moved_old = True
                os.rename(new_dir, old_dir)
                moved_new = True
                if restored_config.exists():
                    original_config.parent.mkdir(exist_ok=True)
                    if original_config.exists():
                        os.rename(original_config, backup_config)
                        saved_config = True
                    os.rename(restored_config, original_config)
            except Exception:
                # Restore old configuration and old data if installation fails.
                if saved_config:
                    original_config.unlink(missing_ok=True)
                    os.rename(backup_config, original_config)
                if moved_new:
                    os.rename(old_dir, stage / 'failed-data')
                if moved_old:
                    os.rename(preserved, old_dir)
                raise
            finally:
                fcntl.flock(new_fd, fcntl.LOCK_UN)
                os.close(new_fd)
        return {'restored': True, 'name': name, 'files': checked['files'],
                'previous_data': preserved.name,
                'previous_config': backup_config.name if saved_config else None}
