
#include "memory_manager.h"

#include <cassert>
#include <iostream>
#include <list>
#include <string>

using std::cout;

void testMemoryUsage() {
    MemoryManager manager(1000);

    manager.update("a", 100);
    manager.update("b", 200);

    assert(manager.usedBytes() == 300);
    assert(manager.maxBytes() == 1000);
    assert(!manager.isFull());

    manager.remove("a");

    assert(manager.usedBytes() == 200);

    std::cout << "Memory usage test passed.\n";
}

void testUpdateExistingKey() {
    MemoryManager manager(1000);

    manager.update("a", 100);
    manager.update("a", 250);

    assert(manager.usedBytes() == 250);

    std::cout << "Update existing key test passed.\n";
}

void testLruOrder() {
    MemoryManager manager(1000);

    manager.update("a", 100);
    manager.update("b", 200);
    manager.update("c", 300);

    // Make a the most recently used key
    manager.touch("a");

    // Only 100 more bytes are needed
    auto candidates = manager.getEvictionCandidates(500);

    assert(candidates.size() == 1);
    assert(candidates.front() == "b");

    cout << "LRU order test passed\n";
}


void testNoEvictionNeeded() {
    MemoryManager manager(1000);

    manager.update("a", 100);
    manager.update("b", 200);

    std::list<std::string> candidates =
        manager.getEvictionCandidates(500);

    assert(candidates.empty());

    std::cout << "No eviction needed test passed.\n";
}

void testMemoryLimit() {
    MemoryManager manager(300);

    manager.update("a", 100);
    manager.update("b", 200);

    assert(manager.isFull());

    std::list<std::string> candidates =
        manager.getEvictionCandidates(100);

    assert(candidates.size() == 1);
    assert(candidates.front() == "a");

    std::cout << "Memory limit test passed.\n";
}

int main() {
    testMemoryUsage();
    testUpdateExistingKey();
    testLruOrder();
    testNoEvictionNeeded();
    testMemoryLimit();

    std::cout << "All eviction tests passed.\n";

    return 0;
}
