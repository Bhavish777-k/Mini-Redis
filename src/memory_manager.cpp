#include "memory_manager.h"

#include <list>
#include <mutex>
#include <string>
#include <unordered_map>

MemoryManager::MemoryManager(std::size_t maxBytes)
    : maxBytes_(maxBytes), usedBytes_(0) {
}

void MemoryManager::touch(const std::string& key) {
    std::lock_guard<std::mutex> lock(mutex_);

    auto it = entries_.find(key);

    if (it == entries_.end()) {
        return;
    }

    lruList_.erase(it->second.position);
    lruList_.push_front(key);

    it->second.position = lruList_.begin();
}

void MemoryManager::update(
    const std::string& key,
    std::size_t bytes
) {
    std::lock_guard<std::mutex> lock(mutex_);

    auto it = entries_.find(key);

    if (it != entries_.end()) {
        usedBytes_ -= it->second.bytes;

        lruList_.erase(it->second.position);
        entries_.erase(it);
    }

    lruList_.push_front(key);

    entries_[key] = {bytes, lruList_.begin()};
    usedBytes_ += bytes;
}

void MemoryManager::remove(const std::string& key) {
    std::lock_guard<std::mutex> lock(mutex_);

    auto it = entries_.find(key);

    if (it == entries_.end()) {
        return;
    }

    usedBytes_ -= it->second.bytes;

    lruList_.erase(it->second.position);
    entries_.erase(it);
}

bool MemoryManager::isFull() const {
    std::lock_guard<std::mutex> lock(mutex_);

    return usedBytes_ >= maxBytes_;
}

std::size_t MemoryManager::usedBytes() const {
    std::lock_guard<std::mutex> lock(mutex_);

    return usedBytes_;
}

bool MemoryManager::grow(std::size_t bytes) {
    std::lock_guard<std::mutex> lock(mutex_);
    if (bytes < maxBytes_) return false;
    maxBytes_ = bytes;
    return true;
}

std::size_t MemoryManager::maxBytes() const {
    std::lock_guard<std::mutex> lock(mutex_);
    return maxBytes_;
}

std::list<std::string> MemoryManager::getEvictionCandidates(
    std::size_t requiredBytes,
    const std::string* replacedKey
) {
    std::lock_guard<std::mutex> lock(mutex_);

    std::list<std::string> victims;
    std::size_t remaining = usedBytes_;

    // An overwrite frees the old value's space.
    if (replacedKey) {
        auto old = entries_.find(*replacedKey);
        if (old != entries_.end()) {
            remaining -= old->second.bytes;
        }
    }

    for (auto it = lruList_.rbegin(); it != lruList_.rend(); ++it) {
        if (remaining <= maxBytes_ &&
            requiredBytes <= maxBytes_ - remaining) {
            break;
        }

        if (replacedKey && *it == *replacedKey) {
            continue;
        }

        victims.push_back(*it);
        remaining -= entries_.at(*it).bytes;
    }

    return victims;
}