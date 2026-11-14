"""Interactive terminal for the Fast-KV router."""
from __future__ import annotations

import argparse
import shlex
import sys

from .client import FastKV, FastKVError


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Fast-KV interactive CLI (router endpoint)")
    parser.add_argument("--host", default="127.0.0.1", help="router host")
    parser.add_argument("--port", type=int, default=7001, help="router port (default: 7001)")
    parser.add_argument("--timeout", type=float, default=3.0)
    parser.add_argument("--command", dest="single", help="execute one complete command and exit")
    parser.add_argument("words", nargs="*", help="optional single command, e.g. GET city")
    args = parser.parse_args(argv)
    if args.single and args.words:
        parser.error("Use --command or positional arguments, not both")
    db = FastKV(host=args.host, port=args.port, timeout=args.timeout)
    if args.single or args.words:
        line = args.single or " ".join(args.words)
        try:
            print(db.command(line))
            return 0
        except (FastKVError, ValueError) as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 1

    print(f"Fast-KV CLI → {args.host}:{args.port}  (help, exit)")
    while True:
        try:
            line = input("fastkv> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if not line:
            continue
        if line.lower() in ("exit", "quit"):
            return 0
        if line.lower() in ("help", "?"):
            print("Commands: PING, SET key value, GET key, DEL key, EXISTS key, INCR key, "
                  "EXPIRE key seconds, TTL key, PERSIST key, WHERE key, COUNT, "
                  "CLUSTER STATUS, ALLOCSTATS, OSSTATS. Type exit to quit.")
            print("Current protocol supports only one whitespace-free token per key/value.")
            continue
        # Use shlex so quoted command words are parsed consistently, but quoted
        # values containing whitespace are intentionally rejected: wire protocol lacks escaping.
        try:
            parts = shlex.split(line)
            if any(any(c.isspace() for c in part) for part in parts):
                raise ValueError("Spaces in keys/values are not supported by the server protocol")
            print(db.command(" ".join(parts)))
        except (FastKVError, ValueError) as exc:
            print(f"Error: {exc}", file=sys.stderr)


if __name__ == "__main__":
    raise SystemExit(main())
