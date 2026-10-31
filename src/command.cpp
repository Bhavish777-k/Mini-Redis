#include "command.h"

#include "kv_store.h"
#include "persistence.h"

#include <charconv>
#include <limits>
#include <mutex>
#include <shared_mutex>
#include <string>
#include <vector>

Command::Command(KVStore& store, Persistence& persistence)
    : store_(store), persistence_(persistence) {
}

std::string Command::execute(
    const std::vector<std::string>& parts
) {
    if (parts.empty()) {
        return "ERR empty command";
    }

    const std::string& name = parts[0];

    if (name == "PING") {
        return "PONG";
    }

    if (name == "SET") {
        if (parts.size() != 3) {
            return "ERR usage: SET key value";
        }

        std::unique_lock<std::shared_mutex> writeLock(writeMutex_);
        return saveValue(parts[1], parts[2]);
    }

    if (name == "GET") {
        if (parts.size() != 2) {
            return "ERR usage: GET key";
        }

        std::shared_lock<std::shared_mutex> readLock(writeMutex_);
        std::string value;

        if (!store_.get(parts[1], value)) {
            return "(nil)";
        }

        return value;
    }

    if (name == "DEL") {
        if (parts.size() != 2) {
            return "ERR usage: DEL key";
        }

        std::unique_lock<std::shared_mutex> writeLock(writeMutex_);

        if (!store_.exists(parts[1])) {
            return "0";
        }

        if (!persistence_.save("DEL " + parts[1])) {
            return "ERR could not save command";
        }

        return store_.del(parts[1]) ? "1" : "0";
    }

    if (name == "EXISTS") {
        if (parts.size() != 2) {
            return "ERR usage: EXISTS key";
        }

        std::shared_lock<std::shared_mutex> readLock(writeMutex_);
        return store_.exists(parts[1]) ? "1" : "0";
    }

    if (name == "INCR") {
        if (parts.size() != 2) {
            return "ERR usage: INCR key";
        }

        // Hold the same lock from reading the counter through saving it.
        std::unique_lock<std::shared_mutex> writeLock(writeMutex_);

        std::string currentValue;
        long long number = 0;

        if (store_.get(parts[1], currentValue)) {
            const char* first = currentValue.data();
            const char* last = first + currentValue.size();

            auto result = std::from_chars(first, last, number);

            if (result.ec != std::errc{} || result.ptr != last) {
                return "ERR value is not an integer";
            }
        }

        if (number == std::numeric_limits<long long>::max()) {
            return "ERR integer overflow";
        }

        const std::string newValue = std::to_string(number + 1);
        const std::string status = saveValue(parts[1], newValue);

        if (status != "OK") {
            return status;
        }

        return newValue;
    }

    if (name == "STATS") {
        std::shared_lock<std::shared_mutex> lock(writeMutex_);
        return "used_bytes=" + std::to_string(store_.usedBytes()) +
               " max_bytes=" + std::to_string(store_.maxBytes()) +
               " keys=" + std::to_string(store_.count());
    }

    if (name == "COUNT") {
        std::shared_lock<std::shared_mutex> readLock(writeMutex_);
        return std::to_string(store_.count());
    }

    if (name == "KEYS") {
        return "ERR KEYS is not implemented yet";
    }

    return "ERR unknown command";
}

std::string Command::saveValue(
    const std::string& key,
    const std::string& value
) {
    const auto victims = store_.evictionsForSet(key, value);

    if (!victims) {
        return "ERR key and value exceed memory limit";
    }

    // Log the write and its evictions together so recovery replays both.
    std::string record = victims->empty() ? "SET " : "SET_EVICT ";
    record += key + " " + value;

    for (const auto& victim : *victims) {
        record += " " + victim;
    }

    if (!persistence_.save(record)) {
        return "ERR could not save command";
    }

    for (const auto& victim : *victims) {
        store_.del(victim);
    }

    store_.set(key, value);
    return "OK";
}