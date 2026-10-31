
#include "thread_pool.h"

#include <utility>

ThreadPool::ThreadPool(std::size_t threadCount)
    : stopping_(false) {
    if (threadCount == 0) {
        threadCount = 2;
    }

    for (std::size_t i = 0; i < threadCount; ++i) {
        workers_.emplace_back(&ThreadPool::worker, this);
    }
}

ThreadPool::~ThreadPool() {
    stop();
}

bool ThreadPool::enqueue(std::function<void()> task) {
    {
        std::lock_guard<std::mutex> lock(mutex_);

        if (stopping_) {
            return false;
        }

        tasks_.push(std::move(task));
    }

    condition_.notify_one();
    return true;
}

void ThreadPool::worker() {
    while (true) {
        std::function<void()> task;

        {
            std::unique_lock<std::mutex> lock(mutex_);

            condition_.wait(lock, [this]() {
                return stopping_ || !tasks_.empty();
            });

            if (stopping_ && tasks_.empty()) {
                return;
            }

            task = std::move(tasks_.front());
            tasks_.pop();
        }

        try {
            task();
        }
        catch (...) {
            // Keep the worker alive if a task fails.
        }
    }
}

void ThreadPool::stop() {
    {
        std::lock_guard<std::mutex> lock(mutex_);

        if (stopping_) {
            return;
        }

        stopping_ = true;
    }

    condition_.notify_all();

    for (std::thread& workerThread : workers_) {
        if (workerThread.joinable()) {
            workerThread.join();
        }
    }

    workers_.clear();
}
