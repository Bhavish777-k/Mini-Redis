
#ifndef MEMORY_MANAGER_H
#define MEMORY_MANAGER_H

#include <cstddef>
#include <list>
#include <mutex>
#include <string>
#include <unordered_map>

class MemoryManager {
public:
    explicit MemoryManager(std::size_t maxBytes);

    MemoryManager(const MemoryManager&) = delete;
    MemoryManager& operator=(const MemoryManager&) = delete;

    // Record a key as recently used
    void touch(const std::string& key);

    // Add or update a key's memory usage
    void update(
        const std::string& key,
        std::size_t bytes
    );

    // Remove a key from memory tracking
    void remove(const std::string& key);

    // Check whether the memory limit is reached
    bool isFull() const;

    // Return current tracked memory usage
    std::size_t usedBytes() const;

    // Return the configured memory limit
    std::size_t maxBytes() const;
    bool grow(std::size_t bytes);

    // Return keys to evict to make room
    std::list<std::string> getEvictionCandidates(
    std::size_t requiredBytes,
    const std::string* replacedKey = nullptr
);

private:
    struct Entry {
        std::size_t bytes;
        std::list<std::string>::iterator position;
    };

    std::size_t maxBytes_;

    std::size_t usedBytes_;
    std::list<std::string> lruList_;
    std::unordered_map<std::string, Entry> entries_;

    mutable std::mutex mutex_;
};

#endif