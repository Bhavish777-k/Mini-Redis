#include "kv_store.h"
#include "slab_allocator.h"

#include <atomic>
#include <cassert>
#include <cstdint>
#include <iostream>
#include <string>
#include <thread>
#include <vector>

int main() {
    // Correct alignment, class selection, free-list reuse.
    SlabResource resource;
    void* p = resource.allocate(100, alignof(std::max_align_t));
    assert(reinterpret_cast<std::uintptr_t>(p) % alignof(std::max_align_t) == 0);
    assert(resource.stats().reservedBytes >= 4096);
    assert(resource.stats().liveBytes == 128);
    assert(resource.stats().internalWasteBytes == 28);
    resource.deallocate(p, 100, alignof(std::max_align_t));
    assert(resource.stats().liveBytes == 0);
    void* q = resource.allocate(100, alignof(std::max_align_t));
    assert(q == p);
    assert(resource.stats().reusedAllocations >= 1);
    resource.deallocate(q, 100, alignof(std::max_align_t));

    // Requests beyond the slabs use operator new/delete; no cached large values.
    p = resource.allocate(1024, alignof(std::max_align_t));
    assert(resource.stats().largeLiveBytes == 1024);
    resource.deallocate(p, 1024, alignof(std::max_align_t));
    assert(resource.stats().largeLiveBytes == 0);

    p = resource.allocate(97, 64);
    assert(reinterpret_cast<std::uintptr_t>(p) % 64 == 0);
    resource.deallocate(p, 97, 64);

    // Concurrent allocation/deallocation protects the shared free lists.
    std::vector<std::thread> threads;
    for (int t = 0; t < 8; ++t) {
        threads.emplace_back([&resource, t]() {
            for (int i = 0; i < 1000; ++i) {
                const auto bytes = static_cast<std::size_t>(24 + ((i + t) % 15) * 19);
                void* p = resource.allocate(bytes, 8);
                resource.deallocate(p, bytes, 8);
            }
        });
    }
    for (auto& thread : threads) thread.join();
    assert(resource.stats().liveBytes == 0);

    // Integration: values in KVStore actually use the slab resource.
    KVStore store(4096);
    const auto before = store.allocatorStats();
    store.set("key", std::string(110, 'a'));
    std::string output;
    assert(store.get("key", output) && output == std::string(110, 'a'));
    assert(store.usedBytes() == 113); // logical payload budget unchanged
    const auto active = store.allocatorStats();
    assert(active.liveBytes > before.liveBytes);
    assert(store.del("key"));
    const auto deleted = store.allocatorStats();
    assert(deleted.liveBytes < active.liveBytes);
    store.set("other", std::string(110, 'b'));
    assert(store.allocatorStats().reusedAllocations > deleted.reusedAllocations);

    std::cout << "PASS: slab classes, reuse, alignment, fallback, threads, KVStore integration\n";
}
