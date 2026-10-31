# Fast-KV: Concurrent In-Memory Key-Value Server

## 1. About the Project

Fast-KV is a C++ key-value server inspired by Redis. It stores data in memory and allows clients to access and modify it through a TCP connection.

The main goal of this project is to understand operating system concepts and build a fast, concurrent server.

## 2. Features

- Store and retrieve key-value pairs
- Support multiple client connections
- Use a thread pool to process client requests
- Protect shared data using mutexes and reader-writer locks
- Support commands such as SET, GET, DEL, EXISTS, and INCR
- Save data to an append-only log file
- Recover stored data after restarting the server
- Manage memory usage with an LRU eviction policy
- Measure request throughput and response latency
- Demonstrate process management, race conditions, and deadlocks

## 3. Technologies Used

- C++20
- CMake
- POSIX (BSD) sockets for TCP networking on Linux
- Standard C++ threading library
- `std::unordered_map` for key-value storage
- `std::shared_mutex` for synchronization
- File handling for persistence
- CTest for running tests

## 4. Project Structure

```text
mini_redis/
├── CMakeLists.txt
├── README.md
├── include/
├── src/
├── tests/
├── benchmarks/
├── demos/
└── data/
    └── appendonly.log   (created automatically when the server runs)
```

## 5. Running the Project on Linux (Step by Step)

These steps were tested on Ubuntu 24.04 (GCC 13, CMake 3.28). They also work on Debian, Linux Mint, WSL2 and similar. Every command is typed in the Linux terminal.

### Step 1: Install the required tools

Ubuntu / Debian / Mint:

```bash
sudo apt update
sudo apt install -y build-essential cmake netcat-openbsd unzip
```

Fedora:

```bash
sudo dnf install -y gcc-c++ cmake make nmap-ncat unzip
```

Arch:

```bash
sudo pacman -S --needed base-devel cmake openbsd-netcat unzip
```

`build-essential` provides `g++` and `make`. A C++20 compiler (GCC 10 or newer, or Clang 12 or newer) and CMake 3.20 or newer are required. `netcat` is only used to talk to the server by hand.

### Step 2: Check the installed versions

```bash
g++ --version
cmake --version
```

### Step 3: Get the project and open it in the terminal

If you have the project as a zip file:

```bash
unzip mini_redis.zip
cd mini_redis
```

Check that you are in the right folder. You should see `CMakeLists.txt`:

```bash
ls
```

### Step 4: Configure and build

```bash
cmake -S . -B build
cmake --build build -j"$(nproc)"
```

The build type defaults to `Release` (optimized). The binaries are placed in the `build/` folder:

```text
build/fast-kv            the server
build/benchmark_client   the benchmark client
build/process_demo       process management demo
build/race_demo          race condition demo
build/deadlock_demo      deadlock demo
build/test_*             unit tests
```

### Step 5: Run the unit tests

```bash
ctest --test-dir build --output-on-failure
```

All 5 tests (Protocol, KVStore, Concurrency, Persistence, Eviction) should show `Passed`.

### Step 6: Start the server (Terminal 1)

```bash
./build/fast-kv
```

You should see:

```text
Starting Fast-KV server...
Workers: 4
Press Ctrl+C to stop.
Server listening on port 6379
```

Leave this terminal open. The server listens on TCP port **6379**. Run it from the project root folder, because data is saved to `data/appendonly.log` relative to the current directory.

If you already have a real Redis running on port 6379, stop it first (`sudo systemctl stop redis-server`) or the bind will fail.

### Step 7: Send commands to the server (Terminal 2)

Open a second terminal and connect with netcat:

```bash
nc 127.0.0.1 6379
```

Now type commands, one per line, and press Enter:

```text
SET name alice
GET name
EXISTS name
INCR counter
INCR counter
DEL name
GET name
```

Expected replies: `OK`, `alice`, `1`, `1`, `2`, `1`, `(nil)`. Press `Ctrl+C` to leave netcat.

You can also send a single command without an interactive session:

```bash
echo "SET city pune" | nc -q1 127.0.0.1 6379
echo "GET city"      | nc -q1 127.0.0.1 6379
```

(On some distributions the flag is `-N` instead of `-q1`.)

### Step 8: Check persistence and recovery

1. In Terminal 1, press `Ctrl+C` to stop the server. It prints `Server stopped.`
2. Look at the saved log:

   ```bash
   cat data/appendonly.log
   ```

3. Start the server again with `./build/fast-kv`, then run `echo "GET counter" | nc -q1 127.0.0.1 6379`. The value from before the restart is returned.

To start with an empty database, delete the log: `rm -f data/appendonly.log`.

### Step 9: Run the benchmark

With the server running in Terminal 1, run in Terminal 2:

```bash
./build/benchmark_client 10000
```

The argument is the number of requests (default 10000). It prints requests per second and average latency.

### Step 10: Run the OS demos

```bash
./build/process_demo     # fork() + exec + waitpid()
./build/race_demo        # data race without a lock vs. with a mutex
./build/deadlock_demo    # two threads locking in opposite order
```

### Rebuilding from scratch

```bash
rm -rf build
cmake -S . -B build
cmake --build build -j"$(nproc)"
```

To build with debug symbols instead: `cmake -S . -B build -DCMAKE_BUILD_TYPE=Debug`.

### Troubleshooting

| Problem | Fix |
|---|---|
| `cmake: command not found` | Install it: `sudo apt install cmake` |
| `g++: command not found` | `sudo apt install build-essential` |
| `Bind failed: Address already in use` | Another program uses port 6379. Find it with `ss -ltnp \| grep 6379` and stop it. |
| `Could not open persistence file` | Run the server from the project folder, and make sure you can write to it. |
| `nc: command not found` | `sudo apt install netcat-openbsd` |
| `Could not connect to Fast-KV` (benchmark) | Start the server first (Step 6). |
| Compiler too old (C++20 errors) | Use GCC 10+ / Clang 12+. On Ubuntu 20.04: `sudo apt install g++-10` and add `-DCMAKE_CXX_COMPILER=g++-10` to the cmake configure command. |

## 6. Changes Made for Linux

The project was originally written for Windows. It was ported as follows:

- **Networking** (`server.h`, `server.cpp`, `event_loop.h`, `event_loop.cpp`, `benchmark_client.cpp`): Winsock2 (`WSAStartup`, `SOCKET`, `closesocket`, `WSAGetLastError`) was replaced with POSIX sockets (`<sys/socket.h>`, `int` file descriptors, `close`, `errno`).
- **Event loop**: `select()` now receives the highest file descriptor + 1 and a rebuilt `fd_set`, as Linux requires (Windows ignores that argument and exposes `fd_array`).
- **Process demo** (`process_demo.cpp`): `CreateProcess` / `WaitForSingleObject` was replaced with `fork` / `exec` / `waitpid`.
- **SIGPIPE**: sending to a disconnected client would kill the process on Linux, so `send()` uses `MSG_NOSIGNAL` and `SIGPIPE` is ignored.
- **Clean shutdown**: `Ctrl+C` (SIGINT) and SIGTERM now stop the server. A watcher thread calls `Server::stop()`, which wakes up `accept()` and any idle client connections so the thread pool can exit.
- **Restarting quickly**: `SO_REUSEADDR` is set on the listening socket.
- **Build** (`CMakeLists.txt`): removed `ws2_32` and MSVC options, defaults to a Release build, and added the missing `protocol.cpp` to `test_persistence`.
- **Other fixes**: removed a stray Markdown code fence from `server.h`, added a missing `std::` in `test_eviction.cpp`, and converted Windows (CRLF) line endings to Linux (LF).

## 7. Performance Testing

The benchmark client will be used to measure:

- Requests processed per second
- Average response time
- p50, p95, and p99 latency
- CPU and memory usage
- Behavior under multiple concurrent clients

Performance comparisons should use the same commands, data sizes, client counts, and persistence settings.

## 8. Project Development Plan

1. Create the basic TCP server.
2. Implement command parsing and key-value storage.
3. Add SET, GET, DEL, EXISTS, and INCR.
4. Add a thread pool and thread-safe operations.
5. Add persistence and recovery.
6. Implement memory limits and LRU eviction.
7. Improve networking and concurrent request handling.
8. Add tests, benchmarks, and operating-system demonstrations.

## 9. Important Note

This is an educational Redis-inspired server. It is not initially a drop-in replacement for Redis. Production use requires additional work on protocol compatibility, persistence guarantees, failure recovery, security, and performance testing.
