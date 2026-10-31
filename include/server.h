#ifndef SERVER_H
#define SERVER_H

#include <atomic>

class KVStore;
class Persistence;
class ThreadPool;

class Server {
public:
    Server(int port, KVStore& store, ThreadPool& pool, Persistence& persistence);
    bool start();
    void stop();

private:
    int port_;
    KVStore& store_;
    ThreadPool& pool_;
    Persistence& persistence_;
    std::atomic<bool> stopping_{false};
};

#endif
