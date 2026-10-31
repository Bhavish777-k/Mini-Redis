
#include "kv_store.h"
#include "persistence.h"

#include <cassert>
#include <filesystem>
#include <iostream>
#include <string>

void testSaveAndLoad() {
    const std::string fileName =
        "test_appendonly.log";

    std::filesystem::remove(fileName);

    {
        KVStore store;
        Persistence persistence(fileName);

        assert(persistence.open());

        assert(persistence.save("SET name Rahul"));
        assert(persistence.save("SET score 95"));
        assert(persistence.save("DEL oldkey"));

        persistence.close();
    }

    {
        KVStore store;
        Persistence persistence(fileName);

        assert(persistence.load(store));

        std::string value;

        assert(store.get("name", value));
        assert(value == "Rahul");

        assert(store.get("score", value));
        assert(value == "95");

        assert(!store.exists("oldkey"));
    }

    std::filesystem::remove(fileName);

    std::cout << "Save and load test passed.\n";
}

void testMissingLog() {
    const std::string fileName =
        "missing_test_log.log";

    std::filesystem::remove(fileName);

    KVStore store;
    Persistence persistence(fileName);

    assert(persistence.load(store));
    assert(store.count() == 0);

    std::cout << "Missing log test passed.\n";
}

int main() {
    testSaveAndLoad();
    testMissingLog();

    std::cout << "All persistence tests passed.\n";
    return 0;
}
