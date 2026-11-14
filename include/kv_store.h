#ifndef KV_STORE_H
#define KV_STORE_H

#include <array>
#include <cstddef>
#include <shared_mutex>
#include <string>
#include <unordered_map>
#include <list>
#include <optional>
#include <vector>
#include <memory_resource>

#include "slab_allocator.h"

#include "memory_manager.h"

class KVStore {
public:
    explicit KVStore(std::size_t maxBytes = 1024 * 1024);
    bool grow(std::size_t bytes) { return memoryManager_.grow(bytes); }
    std::size_t usedBytes() const { return memoryManager_.usedBytes(); }
    std::size_t maxBytes() const { return memoryManager_.maxBytes(); }
    SlabResource::Stats allocatorStats() const { return slab_.stats(); }

    KVStore(const KVStore&) = delete;
    KVStore& operator=(const KVStore&) = delete;

    // Store a value
    void set(const std::string& key, const std::string& value);

    // Get a value
    bool get(const std::string& key, std::string& value) const;

    // Delete a key
    bool del(const std::string& key);

    // Check whether a key exists
    bool exists(const std::string& key) const;

    // Return the number of keys
    std::size_t count() const;

    // Bounded lexicographic page, without building a full key snapshot.
    // Best-effort under concurrent writes; new keys before the cursor may be missed.
    std::vector<std::string> scanAfter(const std::string& cursor,
        const std::string& prefix, std::size_t limit) const;

    std::optional<std::list<std::string>> evictionsForSet(
    const std::string& key,
    const std::string& value
) const;

private:
    static constexpr std::size_t SHARD_COUNT = 64;

    struct Shard {
        mutable std::shared_mutex mutex;
        std::unordered_map<std::string, std::pmr::string> data;
    };

    // Declared before shards_, so pooled values are destroyed before the resource.
    SlabResource slab_;
    std::array<Shard, SHARD_COUNT> shards_;
    mutable MemoryManager memoryManager_;

    // Find the shard for a key
    std::size_t getShardIndex(const std::string& key) const;
};

#endif