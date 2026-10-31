
#include <iostream>
#include <thread>
#include <mutex>
#include <vector>

using namespace std;

int counter = 0;
mutex counterMutex;

void increaseWithoutLock() {
    for (int i = 0; i < 100000; i++) {
        counter++;
    }
}

void increaseWithLock() {
    for (int i = 0; i < 100000; i++) {
        lock_guard<mutex> lock(counterMutex);
        counter++;
    }
}

int main() {
    vector<thread> threads;

    // Run without a mutex
    counter = 0;

    for (int i = 0; i < 4; i++) {
        threads.emplace_back(increaseWithoutLock);
    }

    for (auto& t : threads) {
        t.join();
    }

    cout << "Without mutex: " << counter << '\n';
    cout << "Expected value: 400000\n";

    // Run with a mutex
    counter = 0;
    threads.clear();

    for (int i = 0; i < 4; i++) {
        threads.emplace_back(increaseWithLock);
    }

    for (auto& t : threads) {
        t.join();
    }

    cout << "With mutex: " << counter << '\n';
    cout << "Expected value: 400000\n";

    return 0;
}
