
#include "kv_store.h"

#include <cassert>
#include <iostream>
#include <string>
#include <thread>
#include <vector>

void testMultipleWriters() {
    KVStore store;

    const int threadCount = 8;
    const int keysPerThread = 1000;

    std::vector<std::thread> threads;

    for (int i = 0; i < threadCount; ++i) {
        threads.emplace_back([&store, i]() {
            for (int j = 0; j < 1000; ++j) {
                std::string key =
                    "key_" + std::to_string(i) + "_" +
                    std::to_string(j);

                store.set(key, std::to_string(j));
            }
        });
    }

    for (std::thread& thread : threads) {
        thread.join();
    }

    assert(store.count() == threadCount * keysPerThread);

    std::cout << "Multiple writers test passed.\n";
}

void testConcurrentReadsAndWrites() {
    KVStore store;

    store.set("shared", "0");

    std::vector<std::thread> threads;

    for (int i = 0; i < 4; ++i) {
        threads.emplace_back([&store]() {
            for (int j = 0; j < 5000; ++j) {
                store.set("shared", std::to_string(j));

                std::string value;
                store.get("shared", value);
            }
        });
    }

    for (std::thread& thread : threads) {
        thread.join();
    }

    std::string value;

    assert(store.get("shared", value));
    assert(!value.empty());

    std::cout << "Concurrent reads and writes test passed.\n";
}

void testConcurrentDifferentKeys() {
    KVStore store;

    std::vector<std::thread> threads;

    for (int i = 0; i < 8; ++i) {
        threads.emplace_back([&store, i]() {
            for (int j = 0; j < 500; ++j) {
                std::string key =
                    "user_" + std::to_string(i) + "_" +
                    std::to_string(j);

                store.set(key, "student");

                std::string value;
                assert(store.get(key, value));
                assert(value == "student");
            }
        });
    }

    for (std::thread& thread : threads) {
        thread.join();
    }

    assert(store.count() == 4000);

    std::cout << "Different keys test passed.\n";
}

int main() {
    testMultipleWriters();
    testConcurrentReadsAndWrites();
    testConcurrentDifferentKeys();

    std::cout << "All concurrency tests passed.\n";

    return 0;
}
