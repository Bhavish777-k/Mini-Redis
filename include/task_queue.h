
#ifndef TASK_QUEUE_H
#define TASK_QUEUE_H

#include <condition_variable>
#include <cstddef>
#include <mutex>
#include <queue>

template <typename T>
class TaskQueue {
public:
    explicit TaskQueue(std::size_t maxSize)
        : maxSize_(maxSize), closed_(false) {
    }

    TaskQueue(const TaskQueue&) = delete;
    TaskQueue& operator=(const TaskQueue&) = delete;

    // Add an item if the queue has space
    bool push(const T& item) {
        std::lock_guard<std::mutex> lock(mutex_);

        if (closed_ || queue_.size() >= maxSize_) {
            return false;
        }

        queue_.push(item);
        condition_.notify_one();
        return true;
    }

    // Get the next item
    bool pop(T& item) {
        std::unique_lock<std::mutex> lock(mutex_);

        condition_.wait(lock, [this]() {
            return closed_ || !queue_.empty();
        });

        if (queue_.empty()) {
            return false;
        }

        item = queue_.front();
        queue_.pop();
        return true;
    }

    // Stop accepting new items and wake waiting workers
    void close() {
        {
            std::lock_guard<std::mutex> lock(mutex_);
            closed_ = true;
        }

        condition_.notify_all();
    }

    // Check the number of waiting items
    std::size_t size() const {
        std::lock_guard<std::mutex> lock(mutex_);
        return queue_.size();
    }

    bool empty() const {
        std::lock_guard<std::mutex> lock(mutex_);
        return queue_.empty();
    }

private:
    std::queue<T> queue_;
    const std::size_t maxSize_;

    mutable std::mutex mutex_;
    std::condition_variable condition_;

    bool closed_;
};

#endif