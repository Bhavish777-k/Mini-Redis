
#ifndef COMMAND_H
#define COMMAND_H

#include <string>
#include <vector>
#include <mutex>
#include <shared_mutex>


class KVStore;
class Persistence;

class Command {
public:
    Command(KVStore& store, Persistence& persistence);

    std::string execute(
        const std::vector<std::string>& parts
    );

private:
   inline static std::shared_mutex writeMutex_;

std::string saveValue(
    const std::string& key,
    const std::string& value
);
    KVStore& store_;
    Persistence& persistence_;
};

#endif
