
#include "server.h"
#include "kv_store.h"
#include "thread_pool.h"
#include "persistence.h"

#include <algorithm>
#include <atomic>
#include <chrono>
#include <csignal>
#include <iostream>
#include <charconv>
#include <string_view>
#include <thread>

#include <signal.h>

namespace {
    volatile std::sig_atomic_t stopRequested = 0;

    void handleSignal(int signal) {
        if (signal == SIGINT || signal == SIGTERM) {
            stopRequested = 1;
        }
    }

    // Linux: use sigaction, and ignore SIGPIPE so that writing to a
    // client that already disconnected does not kill the server.
    void installSignalHandlers() {
        struct sigaction action {};
        action.sa_handler = handleSignal;
        sigemptyset(&action.sa_mask);
        action.sa_flags = 0;

        sigaction(SIGINT, &action, nullptr);
        sigaction(SIGTERM, &action, nullptr);

        std::signal(SIGPIPE, SIG_IGN);
    }
}

namespace {
bool positiveNumber(std::string_view text, std::size_t& value) {
    const char* end = text.data() + text.size();
    auto parsed = std::from_chars(text.data(), end, value);
    return parsed.ec == std::errc{} && parsed.ptr == end && value > 0;
}
}

int main(int argc, char* argv[]) {
    std::size_t port = 6379;
    std::size_t maxBytes = 1024 * 1024;
    if (argc > 3 || (argc >= 2 && (!positiveNumber(argv[1], port) || port > 65535)) ||
        (argc == 3 && !positiveNumber(argv[2], maxBytes))) {
        std::cerr << "Usage: fast-kv [port 1..65535] [positive capacity in bytes]\n";
        return 1;
    }

    unsigned int cores = std::thread::hardware_concurrency();

    std::size_t workerCount = std::max(
        2u,
        cores == 0 ? 4u : cores
    );

    KVStore store(maxBytes);
    ThreadPool pool(workerCount);
    Persistence persistence("data/appendonly.log");

    if (!persistence.open()) {
        std::cerr << "Could not open persistence file.\n";
        return 1;
    }

    persistence.close();

    if (!persistence.load(store)) {
        std::cerr << "Could not load saved data.\n";
        return 1;
    }

    if (!persistence.open()) {
        std::cerr << "Could not reopen persistence file.\n";
        return 1;
    }

    installSignalHandlers();

    Server server(port, store, pool, persistence);

    std::cout << "Starting Fast-KV server...\n";
    std::cout << "Workers: " << workerCount << '\n';
    std::cout << "Press Ctrl+C to stop.\n";

    // A signal handler may only set a flag, so a small watcher
    // thread notices it and asks the server to stop.
    std::atomic<bool> finished(false);

    std::thread watcher([&server, &finished]() {
        while (!finished.load()) {
            if (stopRequested) {
                server.stop();
                return;
            }

            std::this_thread::sleep_for(
                std::chrono::milliseconds(100)
            );
        }
    });

    bool started = server.start();

    finished.store(true);
    watcher.join();

    if (!started) {
        std::cerr << "Server failed to start.\n";
        persistence.close();
        pool.stop();
        return 1;
    }

    persistence.close();
    pool.stop();

    std::cout << "Server stopped.\n";
    return 0;
}
