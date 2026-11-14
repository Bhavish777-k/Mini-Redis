#ifndef EVENT_LOOP_H
#define EVENT_LOOP_H

#include <poll.h>
#include <unordered_map>
#include <vector>

// Level-triggered I/O readiness reactor. Linux uses epoll, macOS uses kqueue,
// and FASTKV_IO_BACKEND=poll provides a portable control for benchmarks.
// Client fds are registered once and modified only when their interests change.
class EventLoop {
public:
    struct Ready {
        int fd;
        short events;
    };

    EventLoop();
    ~EventLoop();
    EventLoop(const EventLoop&) = delete;
    EventLoop& operator=(const EventLoop&) = delete;

    bool set(int fd, short interest);
    void remove(int fd);
    int wait(std::vector<Ready>& ready, int timeoutMs);
    const char* backendName() const noexcept;

private:
    enum class Backend { Poll, Epoll, Kqueue };
    Backend backend_ = Backend::Poll;
    int queueFd_ = -1;
    std::unordered_map<int, short> interest_;
};

#endif
