
#ifndef METRICS_H
#define METRICS_H

#include <atomic>
#include <chrono>
#include <cstdint>

class Metrics {
public:
    Metrics();

    // Record a completed request
    void recordRequest(
        bool success,
        std::chrono::nanoseconds duration
    );

    // Return total completed requests
    std::uint64_t totalRequests() const;

    // Return successful requests
    std::uint64_t successfulRequests() const;

    // Return failed requests
    std::uint64_t failedRequests() const;

    // Return average request latency in nanoseconds
    double averageLatencyNs() const;

private:
    std::atomic<std::uint64_t> totalRequests_;
    std::atomic<std::uint64_t> successfulRequests_;
    std::atomic<std::uint64_t> failedRequests_;
    std::atomic<std::uint64_t> totalLatencyNs_;
};

#endif
