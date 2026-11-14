#include "event_loop.h"

#include <cerrno>
#include <cstdlib>
#include <cstring>
#include <string_view>
#include <utility>
#include <ctime>
#include <unistd.h>

#if defined(__linux__)
#include <sys/epoll.h>
#elif defined(__APPLE__)
#include <sys/event.h>
#endif

namespace {
constexpr int batchSize = 256;
}

EventLoop::EventLoop() {
    const char* selected = std::getenv("FASTKV_IO_BACKEND");
    if (selected && std::string_view(selected) == "poll") return;
#if defined(__linux__)
    queueFd_ = epoll_create1(EPOLL_CLOEXEC);
    if (queueFd_ >= 0) backend_ = Backend::Epoll;
#elif defined(__APPLE__)
    queueFd_ = kqueue();
    if (queueFd_ >= 0) backend_ = Backend::Kqueue;
#endif
}

EventLoop::~EventLoop() {
    if (queueFd_ >= 0) close(queueFd_);
}

const char* EventLoop::backendName() const noexcept {
    switch (backend_) {
        case Backend::Epoll: return "epoll";
        case Backend::Kqueue: return "kqueue";
        default: return "poll";
    }
}

bool EventLoop::set(int fd, short interest) {
    interest &= static_cast<short>(POLLIN | POLLOUT);
    if (!interest) { remove(fd); return true; }

    auto found = interest_.find(fd);
    short previous = found == interest_.end() ? 0 : found->second;
    if (previous == interest) return true;

#if defined(__linux__)
    if (backend_ == Backend::Epoll) {
        epoll_event event{};
        event.events = EPOLLERR | EPOLLHUP;
        if (interest & POLLIN) event.events |= EPOLLIN;
        if (interest & POLLOUT) event.events |= EPOLLOUT;
        event.data.fd = fd;
        if (epoll_ctl(queueFd_, previous ? EPOLL_CTL_MOD : EPOLL_CTL_ADD,
                      fd, &event) < 0) return false;
    }
#elif defined(__APPLE__)
    if (backend_ == Backend::Kqueue) {
        struct kevent changes[2];
        int n = 0;
        for (auto entry : {std::pair<short, int>{POLLIN, EVFILT_READ},
                           std::pair<short, int>{POLLOUT, EVFILT_WRITE}}) {
            bool had = (previous & entry.first) != 0;
            bool want = (interest & entry.first) != 0;
            if (had == want) continue;
            EV_SET(&changes[n++], fd, entry.second,
                   want ? EV_ADD | EV_ENABLE : EV_DELETE, 0, 0, nullptr);
        }
        if (n && kevent(queueFd_, changes, n, nullptr, 0, nullptr) < 0) return false;
    }
#endif
    interest_[fd] = interest;
    return true;
}

void EventLoop::remove(int fd) {
    auto it = interest_.find(fd);
    if (it == interest_.end()) return;
#if defined(__linux__)
    if (backend_ == Backend::Epoll)
        epoll_ctl(queueFd_, EPOLL_CTL_DEL, fd, nullptr);
#elif defined(__APPLE__)
    if (backend_ == Backend::Kqueue) {
        struct kevent changes[2];
        int n = 0;
        if (it->second & POLLIN)
            EV_SET(&changes[n++], fd, EVFILT_READ, EV_DELETE, 0, 0, nullptr);
        if (it->second & POLLOUT)
            EV_SET(&changes[n++], fd, EVFILT_WRITE, EV_DELETE, 0, 0, nullptr);
        if (n) kevent(queueFd_, changes, n, nullptr, 0, nullptr);
    }
#endif
    interest_.erase(it);
}

int EventLoop::wait(std::vector<Ready>& ready, int timeoutMs) {
    ready.clear();
#if defined(__linux__)
    if (backend_ == Backend::Epoll) {
        epoll_event events[batchSize];
        int n = epoll_wait(queueFd_, events, batchSize, timeoutMs);
        if (n < 0 && errno == EINTR) return 0;
        if (n < 0) return -1;
        for (int i = 0; i < n; ++i) {
            short flags = 0;
            if (events[i].events & EPOLLIN) flags |= POLLIN;
            if (events[i].events & EPOLLOUT) flags |= POLLOUT;
            if (events[i].events & EPOLLHUP) flags |= POLLHUP;
            if (events[i].events & EPOLLERR) flags |= POLLERR;
            ready.push_back({events[i].data.fd, flags});
        }
        return n;
    }
#elif defined(__APPLE__)
    if (backend_ == Backend::Kqueue) {
        struct kevent events[batchSize];
        timespec timeout{timeoutMs / 1000, (timeoutMs % 1000) * 1000000L};
        int n = kevent(queueFd_, nullptr, 0, events, batchSize, &timeout);
        if (n < 0 && errno == EINTR) return 0;
        if (n < 0) return -1;
        for (int i = 0; i < n; ++i) {
            short flags = 0;
            if (events[i].filter == EVFILT_READ) flags |= POLLIN;
            if (events[i].filter == EVFILT_WRITE) flags |= POLLOUT;
            if (events[i].flags & EV_EOF) flags |= POLLHUP;
            if (events[i].flags & EV_ERROR) flags |= POLLERR;
            ready.push_back({static_cast<int>(events[i].ident), flags});
        }
        return n;
    }
#endif
    std::vector<pollfd> watchers;
    watchers.reserve(interest_.size());
    for (const auto& [fd, interest] : interest_)
        watchers.push_back({fd, interest, 0});
    int n = ::poll(watchers.data(), watchers.size(), timeoutMs);
    if (n < 0 && errno == EINTR) return 0;
    if (n < 0) return -1;
    for (auto& p : watchers)
        if (p.revents) ready.push_back({p.fd, p.revents});
    return n;
}
