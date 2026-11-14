#!/usr/bin/env python3
"""Fast-KV offline backup CLI, no third-party dependencies."""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from dashboard.backup_ops import BackupError, archive_path, create_backup, list_backups, restore_backup, verify_archive  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description='Fast-KV offline backup and restore (cluster must be stopped)')
    parser.add_argument('--root', type=Path, default=ROOT, help='Fast-KV repository directory')
    command = parser.add_subparsers(dest='command', required=True)
    command.add_parser('create', help='Create a verified offline backup')
    command.add_parser('list', help='List previously created backups')
    verify = command.add_parser('verify', help='Verify an existing backup')
    verify.add_argument('name')
    restore = command.add_parser('restore', help='Restore with previous data saved aside; requires stopped cluster')
    restore.add_argument('name')
    restore.add_argument('--confirm', required=True, help='Type RESTORE to enable this operation')
    args = parser.parse_args()
    try:
        if args.command == 'create':
            result = create_backup(args.root)
        elif args.command == 'list':
            result = list_backups(args.root)
        elif args.command == 'verify':
            result = verify_archive(archive_path(args.root, args.name))
        else:
            result = restore_backup(args.root, args.name, confirmation=args.confirm)
        print(json.dumps(result, indent=2))
    except (BackupError, OSError) as exc:
        print(f'Fast-KV backup: {exc}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
