"""Compare Fast-KV's poll fallback with its native epoll/kqueue reactor.

Run: python3 benchmarks/compare_event_loops.py ./build-release/fast-kv
Measures response throughput on the same machine; does not claim universal speedups.
"""
import argparse
import os
from pathlib import Path
import socket
import statistics
import subprocess
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def bench(binary, mode, clients, ops_per_client, idle):
    port = free_port()
    env = os.environ.copy()
    if mode == "poll":
        env["FASTKV_IO_BACKEND"] = "poll"
    else:
        env.pop("FASTKV_IO_BACKEND", None)
    with tempfile.TemporaryDirectory(prefix="fastkv_io_bench_") as root:
        with open(Path(root) / "server.log", "w+") as output:
            p = subprocess.Popen([binary, str(port), str(8 * 1024 * 1024)],
                                 cwd=root, env=env, stdout=output,
                                 stderr=subprocess.STDOUT)
            sockets = []
            try:
                for _ in range(150):
                    try:
                        with socket.create_connection(("127.0.0.1", port), timeout=0.1):
                            break
                    except OSError:
                        if p.poll() is not None:
                            raise RuntimeError("server failed to start")
                        time.sleep(0.03)
                else:
                    raise RuntimeError("server startup timeout")

                for _ in range(idle):
                    sockets.append(socket.create_connection(("127.0.0.1", port), timeout=5))

                barrier = threading.Barrier(clients + 1)

                def worker(i):
                    with closing(socket.create_connection(("127.0.0.1", port), timeout=8)) as s:
                        s.settimeout(8)
                        with s.makefile("rwb") as stream:
                            barrier.wait(timeout=10)
                            for j in range(ops_per_client):
                                stream.write(f"SET io_{i}_{j} value_{j}\n".encode())
                                stream.flush()
                                if stream.readline() != b"OK\n":
                                    raise RuntimeError("unexpected write result")
                with ThreadPoolExecutor(max_workers=clients) as pool:
                    futures = [pool.submit(worker, i) for i in range(clients)]
                    start = time.perf_counter()
                    barrier.wait(timeout=10)
                    for task in futures:
                        task.result()
                    duration = time.perf_counter() - start
                return (clients * ops_per_client) / duration
            finally:
                for s in sockets:
                    s.close()
                if p.poll() is None:
                    p.terminate()
                try:
                    p.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    p.kill()
                    p.wait()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("server", help="Path to fast-kv binary")
    parser.add_argument("--clients", type=int, default=12)
    parser.add_argument("--requests", type=int, default=150,
                        help="Requests per active client")
    parser.add_argument("--idle", type=int, default=150,
                        help="Simultaneous idle connections")
    parser.add_argument("--repeats", type=int, default=3)
    args = parser.parse_args()
    binary = str(Path(args.server).resolve())
    if min(args.clients, args.requests, args.repeats) < 1 or args.idle < 0:
        parser.error("invalid connection count, request count or repetitions")
    samples = {"poll": [], "native": []}
    for i in range(args.repeats):
        for mode in ("poll", "native") if i % 2 == 0 else ("native", "poll"):
            rate = bench(binary, mode, args.clients, args.requests, args.idle)
            samples[mode].append(rate)
            print(f"Round {i+1}: {mode:>6} {rate:,.0f} acknowledged SETs/sec")
    print("\n| Mode | Median acknowledged SETs/sec |")
    print("|---|---:|")
    for mode in ("poll", "native"):
        print(f"| {mode} | {statistics.median(samples[mode]):,.0f} |")
    print("Results are machine/workload-specific. No persistence fsync or durability comparison implied.")


if __name__ == "__main__":
    main()
