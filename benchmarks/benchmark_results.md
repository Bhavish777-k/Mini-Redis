# Fast-KV Benchmark Results

## 1. Objective

The objective is to measure the performance of the Fast-KV key-value server by testing request throughput and latency.

## 2. Test Environment

Record the environment before running the benchmark.

| Item | Details |
|---|---|
| Operating system | Linux (e.g. Ubuntu 24.04) |
| CPU | Fill in your CPU model |
| RAM | Fill in installed RAM |
| Compiler | GCC or Clang |
| Build type | Debug or Release |
| Server port | 6379 |
| Client type | Single TCP client |

## 3. Metrics

- **Throughput:** number of successful requests per second.
- **Average latency:** average time taken for a request and its response.
- **Completed requests:** number of requests that received the expected response.

## 4. Benchmark Procedure

1. Build the server in Release mode.
2. Start the server.
3. Build the benchmark client.
4. Run the client with 10,000 requests.
5. Repeat with 50,000 requests.
6. Record the results.
7. Repeat each test several times and compare the measurements.

Example commands:

```bash
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release
cmake --build build -j"$(nproc)"
./build/fast-kv &                      # start the server in the background
./build/benchmark_client 10000
./build/benchmark_client 50000
kill -INT %1                           # stop the server
```

## 5. Results Table

Fill in the measured values after running each test.

| Requests | Run | Time (seconds) | Throughput (req/s) | Average latency (ms) |
|---:|---:|---:|---:|---:|
| 10,000 | 1 | — | — | — |
| 10,000 | 2 | — | — | — |
| 10,000 | 3 | — | — | — |
| 50,000 | 1 | — | — | — |
| 50,000 | 2 | — | — | — |
| 50,000 | 3 | — | — | — |

## 6. Analysis

After running the benchmark, discuss:

- Whether throughput changes as the request count increases.
- Whether latency remains stable across repeated runs.
- Whether CPU usage or memory consumption becomes a bottleneck.
- Whether Release mode performs better than Debug mode.
- How results change when multiple clients run concurrently.

## 7. Limitations

The current benchmark uses one client and sends requests sequentially, waiting for each response before sending the next request. It therefore does not represent a high-concurrency workload.

The measurements include client-side and network round-trip overhead. They should not be treated as pure server execution latency.

## 8. Conclusion

Complete this section after testing. Report the actual measurements, identify bottlenecks, and describe the next optimizations to investigate. Do not claim that Fast-KV supports a particular number of simultaneous users unless that workload has been tested.
