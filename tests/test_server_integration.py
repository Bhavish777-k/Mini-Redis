"""Run from mini_redis: python3 tests/test_server_integration.py"""
import os
import re
import select
import socket
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack, contextmanager
from pathlib import Path
from threading import Barrier

ADDRESS = ("127.0.0.1", 6379)


def expect(actual, expected, label):
    if actual != expected:
        raise AssertionError(f"{label}: expected {expected!r}, got {actual!r}")


@contextmanager
def server(binary, workdir):
    # A terminal gives us the server's startup banner without buffering.
    master, slave = os.openpty()
    try:
        with os.fdopen(slave, "wb") as output:
            proc = subprocess.Popen([binary], cwd=workdir, stdout=output, stderr=output)
        try:
            banner = b""
            deadline = time.monotonic() + 10
            while b"Server listening on port 6379" not in banner:
                remaining = deadline - time.monotonic()
                if remaining <= 0 or not select.select([master], [], [], remaining)[0]:
                    raise RuntimeError("Server startup timed out: " + banner.decode(errors="replace"))
                try:
                    chunk = os.read(master, 4096)
                except OSError:
                    chunk = b""
                if not chunk:
                    raise RuntimeError("Server startup failed: " + banner.decode(errors="replace"))
                banner += chunk
            workers = int(re.search(rb"Workers: (\d+)", banner).group(1))
            yield proc, workers
        finally:
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait()
                    raise RuntimeError("Server did not stop within five seconds")
    finally:
        os.close(master)


@contextmanager
def client():
    with socket.create_connection(ADDRESS, timeout=3) as sock:
        with sock.makefile("rwb") as stream:
            yield stream


def reply(stream):
    line = stream.readline()
    if not line.endswith(b"\n"):
        raise RuntimeError("Server closed connection before sending a complete reply")
    return line[:-1].decode()


def command(stream, text):
    stream.write((text + "\n").encode())
    stream.flush()
    return reply(stream)


def run(binary, root):
    with server(binary, root) as (proc, workers):
        with ExitStack() as idle:
            for _ in range(workers):
                idle.enter_context(client())
            with client() as probe:
                expect(command(probe, "PING"), "PONG", "idle-client probe")
        print(f"PASS  PING with {workers} idle clients")

        with client() as slow, client() as other:
            slow.write(b"PI")
            slow.flush()
            expect(command(other, "PING"), "PONG", "independent client")
            slow.write(b"NG\n")
            slow.flush()
            expect(reply(slow), "PONG", "split PING")
        print("PASS  split command")

        with client() as c:
            c.write(b"SET order 10\nINCR order\nGET order\nDEL order\n")
            c.flush()
            expect([reply(c) for _ in range(4)], ["OK", "11", "11", "1"], "pipeline")
        print("PASS  pipeline ordering")

        with client() as c:
            expect(command(c, "SET counter 0"), "OK", "initialize counter")
        start = Barrier(2)

        def increments():
            with client() as c:
                start.wait(timeout=5)
                return [int(command(c, "INCR counter")) for _ in range(1000)]

        with ThreadPoolExecutor(max_workers=2) as pool:
            jobs = [pool.submit(increments) for _ in range(2)]
            numbers = jobs[0].result() + jobs[1].result()
        expect(sorted(numbers) == list(range(1, 2001)), True, "unique INCR replies")
        with client() as c:
            expect(command(c, "GET counter"), "2000", "final counter")
        print("PASS  2,000 concurrent increments")

        with client() as c:
            # Remove the counter to keep the LRU example to exactly three keys.
            expect(command(c, "DEL counter"), "1", "delete counter")
            value = "x" * 400_000
            for key in ("a", "b"):
                expect(command(c, f"SET {key} {value}"), "OK", "insert " + key)
            expect(command(c, "GET a") == value, True, "touch a")
            expect(command(c, "SET c " + value), "OK", "insert c")
            expect([command(c, "EXISTS " + k) for k in "abc"], ["1", "0", "1"], "live LRU")
            expect(command(c, "SET saved 73"), "OK", "acknowledged write")
        print("PASS  live LRU eviction")
        proc.kill()
        proc.wait(timeout=5)

    log = root / "data" / "appendonly.log"
    original = log.read_bytes()
    with log.open("ab") as out:
        out.write(b"SET broken 42")  # Deliberately omit the newline.

    with server(binary, root), client() as c:
        expect(command(c, "GET saved"), "73", "recovery after SIGKILL")
        expect([command(c, "EXISTS " + k) for k in "abc"], ["1", "0", "1"], "replayed LRU")
        print("PASS  crash recovery and persisted eviction")
        expect(command(c, "GET broken"), "(nil)", "incomplete record")
        expect(command(c, "SET after 99"), "OK", "first append after repair")
        expect(log.read_bytes() == original + b"SET after 99\n", True, "repaired log bytes")
        print("PASS  truncated log recovery and clean append")


if __name__ == "__main__":
    binary = Path(sys.argv[1] if len(sys.argv) > 1 else "build-debug/fast-kv").resolve()
    try:
        if not binary.is_file():
            raise RuntimeError(f"Build fast-kv first. Executable missing: {binary}")
        with tempfile.TemporaryDirectory(prefix="mini_redis_test_") as directory:
            run(binary, Path(directory))
        print("ALL 7 INTEGRATION CHECKS PASSED")
    except (OSError, RuntimeError, AssertionError, subprocess.SubprocessError) as exc:
        sys.exit(f"FAIL: {exc}")