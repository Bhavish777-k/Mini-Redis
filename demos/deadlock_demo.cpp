
#include <iostream>
#include <thread>
#include <mutex>
#include <chrono>

using namespace std;

mutex mutexA;
mutex mutexB;

void firstThread() {
    lock_guard<mutex> lock1(mutexA);

    cout << "Thread 1 locked mutex A\n";
    this_thread::sleep_for(chrono::milliseconds(100));

    if (mutexB.try_lock()) {
        cout << "Thread 1 locked mutex B\n";
        mutexB.unlock();
    } else {
        cout << "Thread 1 could not lock mutex B\n";
    }
}

void secondThread() {
    lock_guard<mutex> lock1(mutexB);

    cout << "Thread 2 locked mutex B\n";
    this_thread::sleep_for(chrono::milliseconds(100));

    if (mutexA.try_lock()) {
        cout << "Thread 2 locked mutex A\n";
        mutexA.unlock();
    } else {
        cout << "Thread 2 could not lock mutex A\n";
    }
}

int main() {
    thread t1(firstThread);
    thread t2(secondThread);

    t1.join();
    t2.join();

    cout << "Both threads finished\n";

    return 0;
}
