"""Check native reactor and portable poll against real TCP clients.
Usage: python3 tests/test_event_loop_io.py ./build-debug/fast-kv
"""
import os
import pathlib
import socket
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def request(stream, command):
    stream.write(command.encode() + b"\n")
    stream.flush()
    result = stream.readline()
    if not result:
        raise AssertionError("server closed connection")
    return result.rstrip(b"\n").decode()


def recvline(sock):
    data = b""
    while not data.endswith(b"\n"):
        part = sock.recv(32)
        if not part:
            raise AssertionError("socket closed during response")
        data += part
        if len(data) > 256:
            raise AssertionError("oversized response")
    return data


def run_mode(binary, mode):
    port = free_port()
    env = os.environ.copy()
    if mode == "poll":
        env["FASTKV_IO_BACKEND"] = "poll"
    else:
        env.pop("FASTKV_IO_BACKEND", None)

    with tempfile.TemporaryDirectory(prefix="fastkv_reactor_") as directory:
        logpath = pathlib.Path(directory) / "server.log"
        with open(logpath, "w+") as log:
            proc = subprocess.Popen([binary, str(port), str(4 * 1024 * 1024)],
                                    cwd=directory, env=env,
                                    stdout=log, stderr=subprocess.STDOUT)
            sockets = []
            try:
                deadline = time.monotonic() + 8
                while True:
                    if proc.poll() is not None:
                        raise AssertionError(f"server exited: {proc.returncode}")
                    try:
                        with socket.create_connection(("127.0.0.1", port), timeout=0.1):
                            break
                    except OSError:
                        if time.monotonic() > deadline:
                            raise AssertionError("server did not start")
                        time.sleep(0.04)

                # Idle connections must not consume worker threads.
                for _ in range(160):
                    s = socket.create_connection(("127.0.0.1", port), timeout=5)
                    s.settimeout(5)
                    sockets.append(s)
                with closing(socket.create_connection(("127.0.0.1", port), timeout=5)) as probe:
                    with probe.makefile("rwb") as stream:
                        assert request(stream, "PING") == "PONG"

                def exercise(client_id):
                    with closing(socket.create_connection(("127.0.0.1", port), timeout=8)) as s:
                        s.settimeout(8)
                        with s.makefile("rwb") as f:
                            for j in range(80):
                                key = f"io_{client_id}_{j}"
                                f.write(f"SET {key} {j}\nGET {key}\n".encode())
                                f.flush()
                                assert f.readline() == b"OK\n"
                                assert f.readline() == f"{j}\n".encode()
                with ThreadPoolExecutor(max_workers=12) as pool:
                    list(pool.map(exercise, range(12)))

                # Long response exercises partial send handling.
                value = "x" * 25000
                with closing(socket.create_connection(("127.0.0.1", port), timeout=5)) as s:
                    s.settimeout(5)
                    with s.makefile("rwb") as f:
                        assert request(f, f"SET long {value}") == "OK"
                        assert request(f, "GET long") == value

                # A half-closed writer must still receive its queued response.
                with closing(socket.create_connection(("127.0.0.1", port), timeout=5)) as s:
                    s.settimeout(5)
                    s.sendall(b"PING\n")
                    s.shutdown(socket.SHUT_WR)
                    assert recvline(s) == b"PONG\n"

                # Previously idle connections remain usable.
                for s in sockets[::20]:
                    s.sendall(b"PING\n")
                    assert recvline(s) == b"PONG\n"
            finally:
                for s in sockets:
                    s.close()
                if proc.poll() is None:
                    proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait()
                log.flush()
                log.seek(0)
                data = log.read()
                expected_backend = "poll"
                if mode == "native":
                    if sys.platform.startswith("linux"):
                        expected_backend = "epoll"
                    elif sys.platform == "darwin":
                        expected_backend = "kqueue"
                if f"I/O backend: {expected_backend}" not in data:
                    raise AssertionError(f"unexpected reactor, expected {expected_backend}: {data}")
                print(f"PASS: {expected_backend}, 160 idle clients, concurrent pipeline, long response, half-close")


if __name__ == "__main__":
    binary = str(pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else
                              "build-debug/fast-kv").resolve())
    run_mode(binary, "poll")
    run_mode(binary, "native")
    print("ALL REACTOR TESTS PASSED")
