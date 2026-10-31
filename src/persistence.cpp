#include "persistence.h"

#include "kv_store.h"
#include "protocol.h"

#include <cstdint>
#include <filesystem>
#include <fstream>
#include <mutex>
#include <string>
#include <system_error>
#include <vector>

Persistence::Persistence(const std::string& fileName)
    : fileName_(fileName), opened_(false) {
}

Persistence::~Persistence() {
    close();
}

bool Persistence::open() {
    std::lock_guard<std::mutex> lock(mutex_);

    if (opened_) {
        return true;
    }

    try {
        std::filesystem::path path(fileName_);

        if (path.has_parent_path()) {
            std::filesystem::create_directories(path.parent_path());
        }
    }
    catch (...) {
        return false;
    }

    file_.open(fileName_, std::ios::out | std::ios::app | std::ios::binary);

    if (!file_.is_open()) {
        return false;
    }

    opened_ = true;
    return true;
}

bool Persistence::save(const std::string& command) {
    std::lock_guard<std::mutex> lock(mutex_);

    if (!opened_ || !file_.is_open()) {
        return false;
    }

    // The newline marks the end of one complete log entry.
    file_ << command << '\n';
    file_.flush();

    return file_.good();
}

bool Persistence::load(KVStore& store) {
    std::lock_guard<std::mutex> lock(mutex_);

    if (opened_) {
        return false;
    }

    std::ifstream input(fileName_, std::ios::binary);

    if (!input.is_open()) {
        // A missing log is expected on the first run.
        // An existing log that cannot be read is an error.
        std::error_code error;
        bool exists = std::filesystem::exists(fileName_, error);
        return !error && !exists;
    }

    std::uintmax_t completeBytes = 0;
    std::string line;

    while (std::getline(input, line)) {
        if (input.eof()) {
            // getline read some text but reached EOF before finding '\n'.
            // This final entry is incomplete. Do not apply it.
            input.close();

            std::error_code error;
            std::filesystem::resize_file(fileName_, completeBytes, error);
            return !error;
        }

        std::vector<std::string> parts = Protocol::parse(line);

        if (!parts.empty() && !applyCommand(parts, store)) {
            // A complete line containing an invalid command is an error.
            return false;
        }

        // getline removes the newline, so count that byte separately.
        completeBytes += line.size() + 1;
    }

    // An empty file or a clean end after a newline is valid.
    return input.eof() && !input.bad();
}

bool Persistence::applyCommand(
    const std::vector<std::string>& parts,
    KVStore& store
) {
    if (parts.empty()) {
        return true;
    }

    const std::string& command = parts[0];

    if (command == "SET" && parts.size() == 3) {
        store.set(parts[1], parts[2]);
        return true;
    }

    if (command == "SET_EVICT" && parts.size() >= 4) {
    for (std::size_t i = 3; i < parts.size(); ++i) {
        store.del(parts[i]);
    }

    store.set(parts[1], parts[2]);
    return true;
}

    if (command == "DEL" && parts.size() == 2) {
        store.del(parts[1]);
        return true;
    }

    return false;
}

void Persistence::close() {
    std::lock_guard<std::mutex> lock(mutex_);

    if (file_.is_open()) {
        file_.close();
    }

    opened_ = false;
}