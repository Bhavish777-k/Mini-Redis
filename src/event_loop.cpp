#include "event_loop.h"

#include <cerrno>

int EventLoop::wait(std::vector<pollfd>& sockets, int timeoutMs) const {
    int ready = ::poll(sockets.data(), sockets.size(), timeoutMs);

    if (ready == -1 && errno == EINTR) {
        return 0;
    }

    return ready;
}
