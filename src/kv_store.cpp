
#include "kv_store.h"

#include <functional>
#include <mutex>
#include <shared_mutex>
#include <string>

KVStore::KVStore(std::size_t maxBytes)
    : memoryManager_(maxBytes) {}

std::size_t KVStore::getShardIndex(
    const std::string& key
) const {
    return std::hash<std::string>{}(key) % SHARD_COUNT;
}

void KVStore::set(
    const std::string& key,
    const std::string& value
) {
    Shard& shard = shards_[getShardIndex(key)];

    std::unique_lock<std::shared_mutex> lock(shard.mutex);

    // Prepare new value first: allocation failures leave an existing value intact.
    std::pmr::string replacement(&slab_);
    replacement.assign(value.data(), value.size());
    auto [it, inserted] = shard.data.try_emplace(key, &slab_);
    (void)inserted;
    it->second.swap(replacement);
    memoryManager_.update(key, key.size() + value.size());
}

bool KVStore::get(
    const std::string& key,
    std::string& value
) const {
    const Shard& shard = shards_[getShardIndex(key)];

    std::shared_lock<std::shared_mutex> lock(shard.mutex);

    auto it = shard.data.find(key);

    if (it == shard.data.end()) {
        return false;
    }

    value.assign(it->second.data(), it->second.size());
    memoryManager_.touch(key);
    return true;
}

bool KVStore::del(const std::string& key) {
    Shard& shard = shards_[getShardIndex(key)];

    std::unique_lock<std::shared_mutex> lock(shard.mutex);

    auto it = shard.data.find(key);

    if (it == shard.data.end()) {
        return false;
    }

    shard.data.erase(it);
    memoryManager_.remove(key);
    return true;
}

bool KVStore::exists(const std::string& key) const {
    const Shard& shard = shards_[getShardIndex(key)];

    std::shared_lock<std::shared_mutex> lock(shard.mutex);

    return shard.data.find(key) != shard.data.end();
}

std::size_t KVStore::count() const {
    std::size_t total = 0;

    for (const Shard& shard : shards_) {
        std::shared_lock<std::shared_mutex> lock(shard.mutex);
        total += shard.data.size();
    }

    return total;
}

std::optional<std::list<std::string>> KVStore::evictionsForSet(
    const std::string& key,
    const std::string& value
) const {
    const std::size_t limit = memoryManager_.maxBytes();

    if (key.size() > limit || value.size() > limit - key.size()) {
        return std::nullopt;
    }

    return memoryManager_.getEvictionCandidates(
        key.size() + value.size(), &key
    );
}