
#ifndef PERSISTENCE_H
#define PERSISTENCE_H

#include <fstream>
#include <mutex>
#include <string>
#include <vector>

class KVStore;

class Persistence {
public:
    explicit Persistence(const std::string& fileName);

    ~Persistence();

    Persistence(const Persistence&) = delete;
    Persistence& operator=(const Persistence&) = delete;

    // Open the log file
    bool open();

    // Save a command to the log
    bool save(const std::string& command);

    // Load saved commands into the store
    bool load(KVStore& store);

    // Close the log file
    void close();

private:
    std::string fileName_;
    std::ofstream file_;
    std::mutex mutex_;
    bool opened_;

    // Apply a saved command during recovery
    bool applyCommand(
        const std::vector<std::string>& parts,
        KVStore& store
    );
};

#endif