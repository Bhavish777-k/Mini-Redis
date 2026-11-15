#include "server.h"
#include "command.h"
#include "event_loop.h"
#include "protocol.h"
#include "thread_pool.h"

#include <fcntl.h>
#include <netinet/in.h>
#include <sys/socket.h>
#include <unistd.h>

#include <cerrno>
#include <chrono>
#include <cstdio>
#include <future>
#include <iostream>
#include <unordered_map>
#include <memory>
#include <string>
#include <utility>
#include <vector>

namespace {
constexpr std::size_t maxLine = 1024 * 1024;

// Each connection keeps its own unfinished input and outgoing reply.
struct Client {
    std::string input;
    std::string reply;
    std::size_t sent = 0;
    bool closeAfterReply = false;
    std::future<std::string> job;
};

bool nonblocking(int fd) {
    int flags = fcntl(fd, F_GETFL, 0);
    return flags >= 0 && fcntl(fd, F_SETFL, flags | O_NONBLOCK) == 0;
}

bool retryable() {
    return errno == EINTR || errno == EAGAIN || errno == EWOULDBLOCK;
}

int openListener(int port) {
    int fd = socket(AF_INET, SOCK_STREAM, 0);
    if (fd < 0) return -1;

    int one = 1;
    setsockopt(fd, SOL_SOCKET, SO_REUSEADDR, &one, sizeof(one));

    sockaddr_in address{};
    address.sin_family = AF_INET;
    address.sin_port = htons(port);
    address.sin_addr.s_addr = htonl(INADDR_LOOPBACK);

    if (!nonblocking(fd) ||
        bind(fd, reinterpret_cast<sockaddr*>(&address), sizeof(address)) < 0 ||
        listen(fd, SOMAXCONN) < 0) {
        int error = errno;
        close(fd);
        errno = error;
        return -1;
    }

    return fd;
}

// Give a worker one complete command. Keep commands from each client in order.
void prepare(Client& c, ThreadPool& pool, Command& commands, int wakeFd) {
    if (!c.reply.empty()) return;

    if (c.job.valid()) {
        if (c.job.wait_for(std::chrono::seconds(0)) == std::future_status::ready) {
            try {
                c.reply = c.job.get();
            } catch (const std::exception&) {
                c.reply = "ERR command failed\n";
            }
        }
        return;
    }

    auto end = c.input.find('\n');
    auto lineSize = end == std::string::npos ? c.input.size() : end;

    if (lineSize > maxLine) {
        c.reply = "ERR request too large\n";
        c.closeAfterReply = true;
        return;
    }

    if (end == std::string::npos) return;

    std::string line = c.input.substr(0, end);
    c.input.erase(0, end + 1);

    auto task = std::make_shared<std::packaged_task<std::string()>>(
        [&commands, line = std::move(line)] {
            auto parts = Protocol::parse(line);
            if (parts.empty()) return std::string("ERR empty command\n");
            if (!Protocol::isValid(parts)) return std::string("ERR invalid command\n");
            return commands.execute(parts) + "\n";
        });

    c.job = task->get_future();

    if (!pool.enqueue([task, wakeFd] {
        (*task)();

        // Wake poll() so it can send the finished reply.
        // If the pipe is full, a wake-up is already waiting.
        while (write(wakeFd, "x", 1) < 0 && errno == EINTR) {}
    })) {
        c.job = {};
        c.reply = "ERR server busy\n";
        c.closeAfterReply = true;
    }
}

// Only the event loop reads or writes client sockets.
bool service(int fd, short events, Client& c) {
    if (events & (POLLERR | POLLNVAL)) return false;

    if (!c.reply.empty() && (events & (POLLOUT | POLLHUP))) {
        auto n = send(fd, c.reply.data() + c.sent, c.reply.size() - c.sent, 0);
        if (n < 0) return retryable() && !(events & POLLHUP);
        if (n == 0) return false;

        c.sent += static_cast<std::size_t>(n);
        if (c.sent == c.reply.size()) {
            c.reply.clear();
            c.sent = 0;
            if (c.closeAfterReply) return false;
        }
    } else if (events & (POLLIN | POLLHUP)) {
        char bytes[4096];
        auto n = recv(fd, bytes, sizeof(bytes), 0);
        if (n < 0) return retryable() && !(events & POLLHUP);
        if (n == 0) return false;
        c.input.append(bytes, static_cast<std::size_t>(n));
    }

    return true;
}
} // namespace

Server::Server(int port, KVStore& store, ThreadPool& pool, Persistence& persistence)
    : port_(port), store_(store), pool_(pool), persistence_(persistence) {}

void Server::stop() {
    stopping_.store(true);
}

bool Server::start() {
    int listener = openListener(port_);
    if (listener < 0) {
        std::perror("listen");
        return false;
    }

    int wake[2];
    if (pipe(wake) < 0) {
        std::perror("pipe");
        close(listener);
        return false;
    }

    if (!nonblocking(wake[0]) || !nonblocking(wake[1])) {
        std::perror("fcntl");
        close(listener);
        close(wake[0]);
        close(wake[1]);
        return false;
    }

    EventLoop loop;
    Command commands(store_, persistence_);
    std::unordered_map<int, Client> clients;
    bool ok = true;
    std::cout << "I/O backend: " << loop.backendName() << '\n';
    std::cout << "Server listening on port " << port_ << '\n';

    if (!loop.set(listener, POLLIN) || !loop.set(wake[0], POLLIN)) {
        std::perror("register listener");
        ok = false;
    }

    auto refresh = [&](int fd, Client& c) -> bool {
        prepare(c, pool_, commands, wake[1]);
        short interest = c.job.valid() ? 0 : (c.reply.empty() ? POLLIN : POLLOUT);
        if (!loop.set(fd, interest)) {
            std::perror("register client");
            return false;
        }
        return true;
    };
    auto drop = [&](int fd) {
        loop.remove(fd);
        close(fd);
        clients.erase(fd);
    };

    while (ok && !stopping_.load()) {
        std::vector<EventLoop::Ready> ready;
        if (loop.wait(ready, 100) < 0) {
            std::perror("wait for I/O");
            ok = false;
            break;
        }

        bool woke = false;
        for (const auto& event : ready) {
            if (event.fd == wake[0]) {
                if (event.events & POLLIN) {
                    char bytes[256];
                    while (read(wake[0], bytes, sizeof(bytes)) > 0) {}
                    woke = true;
                }
            } else if (event.fd == listener) {
                if (event.events & POLLIN) {
                    // Accept bursts without letting an incoming flood starve active clients.
                    for (int i = 0; i < 64; ++i) {
                        int fd = accept(listener, nullptr, nullptr);
                        if (fd < 0) {
                            if (!retryable() && errno != ECONNABORTED) {
                                std::perror("accept");
                                ok = false;
                            }
                            break;
                        }
                        if (!nonblocking(fd)) { close(fd); continue; }
                        auto [it, inserted] = clients.try_emplace(fd);
                        if (!inserted || !refresh(fd, it->second)) drop(fd);
                    }
                }
            } else {
                auto it = clients.find(event.fd);
                if (it == clients.end()) continue;
                if (!service(event.fd, event.events, it->second) ||
                    !refresh(event.fd, it->second)) drop(event.fd);
            }
        }

        // Worker jobs notify the reactor through a nonblocking pipe. Only
        // check pending futures after a wake-up, not on every I/O event.
        if (woke) {
            for (auto it = clients.begin(); it != clients.end();) {
                int fd = it->first;
                Client& c = it->second;
                if (c.job.valid() &&
                    c.job.wait_for(std::chrono::seconds(0)) == std::future_status::ready &&
                    !refresh(fd, c)) {
                    ++it;
                    drop(fd);
                } else ++it;
            }
        }
    }

    close(listener);
    for (const auto& entry : clients) close(entry.first);

    pool_.stop();
    close(wake[0]);
    close(wake[1]);
    return ok;
}
