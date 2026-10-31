
#include "metrics.h"

#include <atomic>
#include <chrono>
#include <cstdint>

Metrics::Metrics()
    : totalRequests_(0),
      successfulRequests_(0),
      failedRequests_(0),
      totalLatencyNs_(0) {
}

void Metrics::recordRequest(
    bool success,
    std::chrono::nanoseconds duration
) {
    totalRequests_.fetch_add(1, std::memory_order_relaxed);

    if (success) {
        successfulRequests_.fetch_add(
            1, std::memory_order_relaxed
        );
    }
    else {
        failedRequests_.fetch_add(
            1, std::memory_order_relaxed
        );
    }

    auto latency = duration.count();

    if (latency > 0) {
        totalLatencyNs_.fetch_add(
            static_cast<std::uint64_t>(latency),
            std::memory_order_relaxed
        );
    }
}

std::uint64_t Metrics::totalRequests() const {
    return totalRequests_.load(std::memory_order_relaxed);
}

std::uint64_t Metrics::successfulRequests() const {
    return successfulRequests_.load(std::memory_order_relaxed);
}

std::uint64_t Metrics::failedRequests() const {
    return failedRequests_.load(std::memory_order_relaxed);
}

double Metrics::averageLatencyNs() const {
    std::uint64_t total = totalRequests();
    
    if (total == 0) {
        return 0.0;
    }

    return static_cast<double>(
        totalLatencyNs_.load(std::memory_order_relaxed)
    ) / static_cast<double>(total);
}
