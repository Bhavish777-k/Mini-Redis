"""Run against a dedicated local Fast-KV benchmark server on port 6379."""

import math
import socket
import statistics
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack

SERVER = ("127.0.0.1", 6379)
CLIENT_COUNTS = (1, 10, 50)
WRITES = 10_000
RUNS = 3


def measure(clients, commands):
    # Use the same commands at every concurrency level. Only the number of
    # connections changes. Open connections before starting the timer.
    with ExitStack() as stack:
        streams = []
        for _ in range(clients):
            sock = stack.enter_context(socket.create_connection(SERVER, timeout=10))
            streams.append(stack.enter_context(sock.makefile("rwb")))

        gate = threading.Barrier(clients + 1, timeout=15)

        def worker(index):
            stream = streams[index]
            times = []
            gate.wait()
            for command in commands[index::clients]:
                begin = time.perf_counter_ns()
                stream.write(command)
                stream.flush()
                response = stream.readline()
                end = time.perf_counter_ns()
                if response != b"OK\n":
                    raise RuntimeError(f"SET failed: {response!r}")
                times.append((end - begin) / 1_000_000)
            return times, end

        with ThreadPoolExecutor(max_workers=clients) as pool:
            jobs = [pool.submit(worker, index) for index in range(clients)]
            begin = time.perf_counter_ns()
            gate.wait()
            results = [job.result() for job in jobs]

    elapsed = (max(end for _, end in results) - begin) / 1_000_000_000
    times = sorted(ms for samples, _ in results for ms in samples)
    p95 = times[math.ceil(0.95 * len(times)) - 1]
    return len(times) / elapsed, statistics.mean(times), p95


def main():
    commands = [f"SET bench_demo_{i} value{i}\n".encode() for i in range(WRITES)]
    results = {clients: [] for clients in CLIENT_COUNTS}

    print(f"Fast-KV | localhost:6379 | {WRITES:,} SETs per run | {RUNS} rounds")
    # Pre-fill once so every timed run overwrites the same existing keys.
    print("Preparing benchmark keys...", flush=True)
    measure(1, commands)

    print("Round  Clients    Writes/s    Avg ms    p95 ms", flush=True)
    for run in range(RUNS):
        # Rotate the order so each client count goes first once.
        offset = run % len(CLIENT_COUNTS)
        for clients in CLIENT_COUNTS[offset:] + CLIENT_COUNTS[:offset]:
            rate, avg, p95 = measure(clients, commands)
            results[clients].append((rate, avg, p95))
            print(f"{run+1:>5}  {clients:>7}  {rate:>10,.0f}  {avg:>8.4f}  {p95:>8.4f}", flush=True)

    print("\nMedian across three runs for each metric (Markdown)\n")
    print("| Clients | Successful SETs per run | Writes/s | Average ms | p95 ms |")
    print("|---:|---:|---:|---:|---:|")
    for clients, runs in results.items():
        rate, avg, p95 = (statistics.median(column) for column in zip(*runs))
        print(f"| {clients} | {WRITES:,} | {rate:,.0f} | {avg:.4f} | {p95:.4f} |")


if __name__ == "__main__":
    try:
        main()
    except ConnectionRefusedError:
        sys.exit("No server on localhost:6379. Start build-release/fast-kv and retry.")
    except (OSError, RuntimeError, threading.BrokenBarrierError) as exc:
        sys.exit(f"Benchmark failed: {exc}")