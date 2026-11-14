#!/usr/bin/env python3
"""Exercise Fast-KV's slab allocator through the real TCP server."""
import pathlib
import socket
import subprocess
import sys
import tempfile
import time


def request(port, command):
    with socket.create_connection(("127.0.0.1", port), timeout=2) as conn:
        conn.sendall((command + "\n").encode("ascii"))
        data = b""
        while b"\n" not in data:
            part = conn.recv(4096)
            if not part:
                raise RuntimeError("Connection closed before response")
            data += part
    return data.split(b"\n", 1)[0].decode("ascii")


def metrics(line):
    result = {}
    for entry in line.split():
        name, value = entry.split("=", 1)
        result[name] = int(value)
    return result


def start_server(binary, port, root):
    proc = subprocess.Popen([str(binary), str(port), "4096"], cwd=root,
                            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    for _ in range(100):
        if proc.poll() is not None:
            raise RuntimeError("Fast-KV exited during startup")
        try:
            if request(port, "PING") == "PONG":
                return proc
        except OSError:
            pass
        time.sleep(.03)
    proc.terminate()
    proc.wait(timeout=5)
    raise RuntimeError("Fast-KV never became ready")


def main():
    binary = pathlib.Path(sys.argv[1]).resolve()
    port = 18471
    with tempfile.TemporaryDirectory(prefix="fastkv-allocator-") as root:
        pathlib.Path(root, "data").mkdir()
        proc = start_server(binary, port, root)
        try:
            before = metrics(request(port, "ALLOCSTATS"))
            assert request(port, "SET long " + "a" * 110) == "OK"
            active = metrics(request(port, "ALLOCSTATS"))
            assert active["slab_live_bytes"] > before["slab_live_bytes"]
            assert request(port, "DEL long") == "1"
            released = metrics(request(port, "ALLOCSTATS"))
            assert released["slab_live_bytes"] < active["slab_live_bytes"]
            assert request(port, "SET long " + "b" * 110) == "OK"
            after = metrics(request(port, "ALLOCSTATS"))
            assert after["slab_reuses"] > released["slab_reuses"]
            assert request(port, "GET long") == "b" * 110
            logical = metrics(request(port, "STATS"))
            assert logical["used_bytes"] == 114
        finally:
            proc.terminate()
            proc.wait(timeout=5)

        proc = start_server(binary, port, root)
        try:
            assert request(port, "GET long") == "b" * 110
        finally:
            proc.terminate()
            proc.wait(timeout=5)

    print("PASS: real TCP ALLOCSTATS, slab reuse, logical quota, persisted restart")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: test_allocator_integration.py PATH_TO_FAST_KV", file=sys.stderr)
        sys.exit(2)
    main()
