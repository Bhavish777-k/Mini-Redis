#ifndef EVENT_LOOP_H
#define EVENT_LOOP_H

#include <poll.h>
#include <vector>

class EventLoop {
public:
    int wait(std::vector<pollfd>& sockets, int timeoutMs) const;
};

#endif
