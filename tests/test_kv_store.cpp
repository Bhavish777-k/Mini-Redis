
#include "kv_store.h"

#include <cassert>
#include <iostream>
#include <string>

void testSetAndGet() {
    KVStore store;

    store.set("name", "Rahul");

    std::string value;

    bool found = store.get("name", value);

    assert(found);
    assert(value == "Rahul");

    std::cout << "Set and get test passed.\n";
}

void testMissingKey() {
    KVStore store;

    std::string value;

    bool found = store.get("unknown", value);

    assert(!found);

    std::cout << "Missing key test passed.\n";
}

void testUpdateValue() {
    KVStore store;

    store.set("score", "80");
    store.set("score", "95");

    std::string value;

    assert(store.get("score", value));
    assert(value == "95");

    std::cout << "Update test passed.\n";
}

void testDelete() {
    KVStore store;

    store.set("city", "Delhi");

    assert(store.del("city"));
    assert(!store.exists("city"));
    assert(!store.del("city"));

    std::cout << "Delete test passed.\n";
}

void testExists() {
    KVStore store;

    store.set("course", "C++");

    assert(store.exists("course"));
    assert(!store.exists("unknown"));

    std::cout << "Exists test passed.\n";
}

void testCount() {
    KVStore store;

    assert(store.count() == 0);

    store.set("a", "1");
    store.set("b", "2");
    store.set("c", "3");

    assert(store.count() == 3);

    store.del("b");

    assert(store.count() == 2);

    std::cout << "Count test passed.\n";
}

int main() {
    testSetAndGet();
    testMissingKey();
    testUpdateValue();
    testDelete();
    testExists();
    testCount();

    std::cout << "All key-value store tests passed.\n";

    return 0;
}
