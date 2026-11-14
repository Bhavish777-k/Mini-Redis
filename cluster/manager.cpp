#include <algorithm>
#include <cctype>
#include <map>
#include <memory>
#include <poll.h>
#include <sstream>
#include <vector>
#include <arpa/inet.h>
#include <fcntl.h>
#include <fstream>
#include <limits>
#include <sys/file.h>
#include <sys/socket.h>
#include <sys/wait.h>
#include <unistd.h>

#include <cerrno>
#include <charconv>
#include <chrono>
#include <csignal>
#include <cstdint>
#include <cstdio>
#include <filesystem>
#include <iostream>
#include <optional>
#include <stdexcept>
#include <string>
#include <string_view>
#include <thread>

namespace {
using namespace std::chrono_literals;
using Bytes = std::uint64_t;
namespace fs = std::filesystem;
volatile std::sig_atomic_t stopping = 0;
void requestStop(int) { stopping = 1; }

bool parseNumber(std::string_view text, Bytes& n) {
    const char* end = text.data() + text.size();
    auto result = std::from_chars(text.data(), end, n);
    return result.ec == std::errc{} && result.ptr == end;
}

struct FD {
    int value;
    explicit FD(int fd) : value(fd) {}
    ~FD() { if (value >= 0) close(value); }
    FD(const FD&) = delete;
    FD& operator=(const FD&) = delete;
};

sockaddr_in addressFor(int port) {
    sockaddr_in address{};
    address.sin_family = AF_INET;
    address.sin_port = htons(port);
    address.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
    return address;
}

struct Stats { Bytes used, max; };

std::optional<Stats> stats(int port) {
    FD fd(socket(AF_INET, SOCK_STREAM, 0));
    if (fd.value < 0) return {};
    timeval timeout{0, 500000};
    if (setsockopt(fd.value, SOL_SOCKET, SO_RCVTIMEO, &timeout, sizeof(timeout)) ||
        setsockopt(fd.value, SOL_SOCKET, SO_SNDTIMEO, &timeout, sizeof(timeout))) return {};
    auto address = addressFor(port);
    if (connect(fd.value, reinterpret_cast<sockaddr*>(&address), sizeof(address))) return {};

    std::string_view request = "STATS\n";
    while (!request.empty()) {
        auto n = send(fd.value, request.data(), request.size(), 0);
        if (n < 0 && errno == EINTR) continue;
        if (n <= 0) return {};
        request.remove_prefix(static_cast<std::size_t>(n));
    }

    std::string reply;
    char buf[128];
    while (reply.find('\n') == std::string::npos) {
        auto n = recv(fd.value, buf, sizeof(buf), 0);
        if (n < 0 && errno == EINTR) continue;
        if (n <= 0 || reply.size() + n > 256) return {};
        reply.append(buf, static_cast<std::size_t>(n));
    }
    std::string_view line(reply.data(), reply.find('\n'));
    if (!line.starts_with("used_bytes=")) return {};
    line.remove_prefix(11);
    auto sep = line.find(" max_bytes=");
    Stats s{};
    if (sep == line.npos || !parseNumber(line.substr(0, sep), s.used)) return {};
    line.remove_prefix(sep + 11);
    sep = line.find(" keys=");
    if (sep == line.npos || !parseNumber(line.substr(0, sep), s.max) || s.max == 0) return {};
    return s;
}

struct Node {
    int port;
    pid_t pid = -1;
    unsigned restartFailures = 0;
    unsigned totalRestarts = 0;
    std::chrono::steady_clock::time_point startedAt{};
    std::chrono::steady_clock::time_point retryAfter{};

    bool alive() {
        if (pid < 0) return false;
        int status;
        pid_t r;
        do { r = waitpid(pid, &status, WNOHANG); } while (r < 0 && errno == EINTR);
        if (r == 0) return true;
        pid = -1;
        return false;
    }

    void terminate() {
        if (!alive()) return;
        kill(pid, SIGTERM);
        for (int i = 0; i < 100 && alive(); ++i) std::this_thread::sleep_for(20ms);
        if (pid > 0) {
            kill(pid, SIGKILL);
            while (waitpid(pid, nullptr, 0) < 0 && errno == EINTR) {}
            pid = -1;
        }
    }

    ~Node() { terminate(); }
};

void start(Node& node, const fs::path& binary, const fs::path& dir, Bytes capacity) {
    auto address = addressFor(node.port);
    {
        FD check(socket(AF_INET, SOCK_STREAM, 0));
        if (check.value < 0) throw std::runtime_error("Cannot create probe socket");
        if (connect(check.value, reinterpret_cast<sockaddr*>(&address), sizeof(address)) == 0)
            throw std::runtime_error("Port " + std::to_string(node.port) + " already has a listener");
        if (errno != ECONNREFUSED) throw std::runtime_error("Cannot check node port");
    }
    fs::create_directories(dir);
    std::string port = std::to_string(node.port);
    std::string bytes = std::to_string(capacity);
    node.pid = fork();
    if (node.pid < 0) throw std::runtime_error("fork failed");
    if (node.pid == 0) {
        if (chdir(dir.c_str()) < 0) { std::perror("chdir"); _exit(1); }
        execl(binary.c_str(), "fast-kv", port.c_str(), bytes.c_str(), static_cast<char*>(nullptr));
        std::perror("exec fast-kv");
        _exit(1);
    }
    for (int i = 0; i < 100 && !stopping; ++i) {
        if (!node.alive()) throw std::runtime_error("Node exited during startup on port " + port);
        auto s = stats(node.port);
        if (s && s->max == capacity) {
            node.startedAt = std::chrono::steady_clock::now();
            std::cout << "READY port=" << port << " pid=" << node.pid << std::endl;
            return;
        }
        std::this_thread::sleep_for(50ms);
    }
    if (!stopping) throw std::runtime_error("Node did not report the expected STATS on port " + port);
}
constexpr int firstPort = 6381;
constexpr unsigned maxLocalNodes = 32;
void saveCapacity(const fs::path& file, Bytes bytes) {
    auto temp = file.string() + ".tmp";
    std::ofstream out(temp, std::ios::trunc);
    out << bytes << '\n';
    out.close();
    if (!out) throw std::runtime_error("could not save node capacity");
    fs::rename(temp, file);
}

Bytes savedCapacity(const fs::path& file) {
    std::ifstream input(file);
    Bytes n = 0;
    std::string token, extra;
    if (!(input >> token) || (input >> extra) || !parseNumber(token, n) || !n)
        throw std::runtime_error("invalid node capacity file: " + file.string());
    return n;
}

struct Cluster {
    fs::path binary;
    Bytes capacity;
    unsigned limit;
    std::vector<std::unique_ptr<Node>> nodes;

    bool active(int port) const {
        return port >= firstPort && static_cast<unsigned>(port - firstPort) < nodes.size();
    }

    int launch() {
        if (nodes.size() >= limit) throw std::runtime_error("cluster capacity reached");
        auto child = std::make_unique<Node>();
        child->port = firstPort + static_cast<int>(nodes.size());
        auto dir = fs::path("cluster-data") / ("node-" + std::to_string(nodes.size()+1));
        fs::create_directories(dir);
        auto file = dir / "capacity.bytes";
        if (!fs::exists(file)) saveCapacity(file, capacity);
        start(*child, binary, dir, savedCapacity(file));
        if (stopping) throw std::runtime_error("manager stopping");
        int port = child->port;
        nodes.push_back(std::move(child));
        return port;
    }

    void restore() {
        unsigned count = 1;
        for (unsigned id = 2; id <= maxLocalNodes; ++id) {
            auto log = fs::path("cluster-data") / ("node-" + std::to_string(id)) /
                       "data/appendonly.log";
            if (fs::exists(log)) {
                if (id != count + 1 || id > limit)
                    throw std::runtime_error("existing nodes exceed limit or node directory is missing");
                count = id;
            }
        }
        while (nodes.size() < count) launch();
    }

    // OS process supervision: restart a crashed node using its original
    // data directory, so the storage server can replay its append-only log.
    // After five consecutive failed restarts, stop to avoid a crash loop.
    void supervise() {
        using Clock = std::chrono::steady_clock;
        auto now = Clock::now();
        for (std::size_t i = 0; i < nodes.size(); ++i) {
            auto& node = *nodes[i];
            if (node.alive()) {
                if (node.startedAt != Clock::time_point{} &&
                    now - node.startedAt >= 60s) node.restartFailures = 0;
                continue;
            }
            if (now < node.retryAfter) continue;
            if (node.restartFailures >= 5)
                throw std::runtime_error("node " + std::to_string(node.port) +
                                         " repeatedly failed to restart");
            ++node.restartFailures;
            std::cerr << "SUPERVISOR crash port=" << node.port
                      << " attempt=" << node.restartFailures << "\n";
            try {
                auto dir = fs::path("cluster-data") /
                           ("node-" + std::to_string(i + 1));
                start(node, binary, dir, capacity);
                ++node.totalRestarts;
                std::cout << "SUPERVISOR recovered port=" << node.port
                          << " pid=" << node.pid << "\n";
            } catch (const std::exception& e) {
                node.terminate(); // clean up a process that started but never became ready
                auto backoff = std::chrono::seconds(1u << node.restartFailures);
                node.retryAfter = Clock::now() + backoff;
                std::cerr << "SUPERVISOR restart failed port=" << node.port
                          << " reason=" << e.what() << "\n";
            }
        }
    }
};

// All node commands go through this loop, so concurrent requests cannot
// choose different homes for the same previously unseen key.
constexpr std::size_t maxLine = 1024 * 1024;
std::string nodeRequest(int port, std::string request) {
    FD fd(socket(AF_INET, SOCK_STREAM, 0));
    timeval limit{1, 0};
    auto addr = addressFor(port);
    if (fd.value < 0 ||
        setsockopt(fd.value, SOL_SOCKET, SO_RCVTIMEO, &limit, sizeof(limit)) ||
        setsockopt(fd.value, SOL_SOCKET, SO_SNDTIMEO, &limit, sizeof(limit)) ||
        connect(fd.value, reinterpret_cast<sockaddr*>(&addr), sizeof(addr)))
        throw std::runtime_error("node unavailable: " + std::to_string(port));
    request += '\n';
    std::size_t offset = 0;
    while (offset < request.size()) {
        auto n = send(fd.value, request.data() + offset, request.size() - offset, 0);
        if (n < 0 && errno == EINTR) continue;
        if (n <= 0) throw std::runtime_error("node send failed; outcome unknown");
        offset += static_cast<std::size_t>(n);
    }
    std::string response;
    char buf[8192];
    while (response.size() <= maxLine) {
        auto n = recv(fd.value, buf, sizeof(buf), 0);
        if (n < 0 && errno == EINTR) continue;
        if (n <= 0) throw std::runtime_error("node reply lost; outcome unknown");
        response.append(buf, static_cast<std::size_t>(n));
        if (response.back() == '\n') { response.pop_back(); return response; }
    }
    throw std::runtime_error("node reply too large");
}

// Only the router writes to the nodes during migration. Its single event loop
// finishes one command before dispatching the next, including MOVE.
const fs::path pendingMove = "cluster-data/pending-move";

bool existsOn(int port, const std::string& key) {
    auto reply = nodeRequest(port, "EXISTS " + key);
    if (reply != "0" && reply != "1") throw std::runtime_error("invalid EXISTS reply");
    return reply == "1";
}

void finishMove(const std::string& key, int source, int dest,
                const std::optional<std::string>& updatedValue) {
    if (existsOn(source, key)) {
        auto value = updatedValue ? *updatedValue : nodeRequest(source, "GET " + key);
        if (!existsOn(dest, key)) {
            auto s = stats(dest);
            if (!s || s->used > s->max || key.size() + value.size() > s->max - s->used)
                throw std::runtime_error("insufficient destination capacity");
            if (nodeRequest(dest, "SET " + key + " " + value) != "OK")
                throw std::runtime_error("destination rejected move");
        }
        if (nodeRequest(dest, "GET " + key) != value)
            throw std::runtime_error("destination verification failed");
        if (nodeRequest(source, "DEL " + key) != "1")
            throw std::runtime_error("source deletion failed");
    } else if (!existsOn(dest, key)) {
        throw std::runtime_error("migrating key missing on both nodes");
    }
    if (updatedValue && nodeRequest(dest, "GET " + key) != *updatedValue)
        throw std::runtime_error("updated value verification failed");
    fs::remove(pendingMove);
}

void recoverMove(const Cluster& cluster) {
    if (!fs::exists(pendingMove)) return;
    std::ifstream input(pendingMove);
    int source, dest;
    std::string key, value, extra;
    if (!(input >> source >> dest >> key) ||
        source == dest || !cluster.active(source) || !cluster.active(dest))
        throw std::runtime_error("invalid pending-move journal");
    std::optional<std::string> update;
    if (input >> value) update = value;
    if (input >> extra) throw std::runtime_error("invalid pending-move journal");
    finishMove(key, source, dest, update);
}

std::string moveKey(const std::string& key, int source, int dest,
                    const std::optional<std::string>& update = {}) {
    bool from = existsOn(source,key), to = existsOn(dest,key);
    if (from && to) return "ERR duplicate key";
    if (!from) return to ? "OK" : "ERR key missing";
    auto value = update ? *update : nodeRequest(source, "GET " + key);
    auto s = stats(dest);
    if (!s) return "ERR destination unavailable";
    if (s->used > s->max || key.size() + value.size() > s->max - s->used)
        return "ERR insufficient destination capacity";
    // Publish a complete intent before changing either node.
    auto temp = pendingMove.string() + ".tmp";
    std::ofstream journal(temp, std::ios::trunc);
    journal << source << ' ' << dest << ' ' << key;
    if (update) journal << ' ' << *update;
    journal << '\n';
    journal.close();
    if (!journal) throw std::runtime_error("cannot record migration");
    fs::rename(temp, pendingMove);
    finishMove(key, source, dest, update);
    return "OK";
}

Bytes freeBytes(const Stats& node) {
    return node.max - std::min(node.used, node.max);
}

int findOwner(const Cluster& cluster, const std::string& key) {
    int owner = 0;
    for (const auto& node : cluster.nodes) {
        if (!existsOn(node->port, key)) continue;
        if (owner) throw std::runtime_error("key exists on multiple nodes");
        owner = node->port;
    }
    return owner;
}

std::string placeValue(const std::string& key, const std::string& value,
                       int owner, const std::optional<std::string>& previous, Cluster& cluster) {
    Bytes size = key.size() + value.size();
    Bytes largest = cluster.capacity;
    int target = 0;
    Bytes bestFree = 0;
    for (const auto& node : cluster.nodes) {
        auto current = stats(node->port);
        if (!current) return "ERR unable to read node capacities";
        largest = std::max(largest, current->max);
        Bytes room = freeBytes(*current);
        if (node->port == owner) {
            Bytes oldSize = key.size() + previous->size();
            if (size <= oldSize || size - oldSize <= room)
                return nodeRequest(owner, "SET " + key + " " + value);
        } else if (room >= size && room > bestFree) {
            bestFree = room;
            target = node->port;
        }
    }
    if (!target) {
        if (size > largest) return "ERR key exceeds node capacity";
        if (size > cluster.capacity || cluster.nodes.size() >= cluster.limit)
            return "ERR cluster capacity reached";
        target = cluster.launch();
    }
    if (owner) return moveKey(key, owner, target, value);
    return nodeRequest(target, "SET " + key + " " + value);
}

std::string route(const std::string& line, Cluster& cluster) {
    std::istringstream in(line);
    std::string op, key, value, extra;
    in >> op;
    for (char& c : op) c = static_cast<char>(std::toupper(static_cast<unsigned char>(c)));
    recoverMove(cluster); // Reconcile any interrupted operation before serving another request.
    if (op == "MOVE") {
        std::string port;
        Bytes number;
        if (!(in >> key >> port) || (in >> extra) || !parseNumber(port, number) ||
            number > 65535 || !cluster.active(static_cast<int>(number)))
            return "ERR MOVE requires a key and an active destination port";
        int owner = findOwner(cluster, key);
        if (!owner) return "ERR key missing";
        if (static_cast<int>(number) == owner) return "OK";
        return moveKey(key, owner, static_cast<int>(number));
    }
    if (op == "CLUSTER" && (in >> key) && key == "STATUS" && !(in >> extra)) {
        std::string reply = "nodes=" + std::to_string(cluster.nodes.size()) +
                            " max_nodes=" + std::to_string(cluster.limit);
        for (const auto& node : cluster.nodes) {
            auto st = stats(node->port);
            reply += " port=" + std::to_string(node->port) + " ";
            reply += st ? std::to_string(st->used) + "/" + std::to_string(st->max) : "unavailable";
            reply += " pid=" + std::to_string(node->pid) +
                     " restarts=" + std::to_string(node->totalRestarts);
        }
        return reply;
    }
    if (op == "PING" && !(in >> extra)) return "PONG";
    if (op == "COUNT" && !(in >> extra)) {
        Bytes sum = 0;
        for (const auto& node : cluster.nodes) {
            Bytes n;
            if (!parseNumber(nodeRequest(node->port, "COUNT"), n)) return "ERR invalid COUNT";
            sum += n;
        }
        return std::to_string(sum);
    }
    if (op != "GET" && op != "SET" && op != "DEL" && op != "INCR" &&
        op != "EXISTS" && op != "WHERE") return "ERR unknown or unsupported command";
    if (!(in >> key) || (op == "SET" && !(in >> value)) || (in >> extra))
        return "ERR invalid arguments";
    int owner = findOwner(cluster, key);
    if (op == "WHERE") return owner ? std::to_string(owner) : "(nil)";
    if (op == "SET" || op == "INCR") {
        std::optional<std::string> previous;
        if (owner) previous = nodeRequest(owner, "GET " + key);
        if (op == "INCR") {
            long long n = 0;
            if (previous) {
                const char* end = previous->data() + previous->size();
                auto parsed = std::from_chars(previous->data(), end, n);
                if (parsed.ec != std::errc{} || parsed.ptr != end)
                    return "ERR value is not an integer";
            }
            if (n == std::numeric_limits<long long>::max()) return "ERR integer overflow";
            value = std::to_string(n + 1);
        }
        auto status = placeValue(key, value, owner, previous, cluster);
        return status == "OK" && op == "INCR" ? value : status;
    }
    if (!owner) return op == "GET" ? "(nil)" : "0";
    return nodeRequest(owner, line);
}

void makeNonblocking(int fd) {
    int flags = fcntl(fd, F_GETFL);
    if (flags < 0 || fcntl(fd, F_SETFL, flags | O_NONBLOCK) < 0)
        throw std::runtime_error("cannot configure socket");
}

struct Client { std::string input, output; std::size_t sent = 0; bool closing = false; };
class Router {
    FD listener{socket(AF_INET, SOCK_STREAM, 0)};
    std::map<int, Client> clients;
public:
    Router() {
        int one = 1;
        auto addr = addressFor(7000);
        if (listener.value < 0 ||
            setsockopt(listener.value, SOL_SOCKET, SO_REUSEADDR, &one, sizeof(one)) ||
            bind(listener.value, reinterpret_cast<sockaddr*>(&addr), sizeof(addr)) ||
            listen(listener.value, 128))
            throw std::runtime_error("cannot listen on localhost:7000");
        makeNonblocking(listener.value);
        std::cout << "ROUTER listening on 127.0.0.1:7000" << std::endl;
    }
    ~Router() { for (auto& entry : clients) close(entry.first); }

    void tick(Cluster& cluster) {
        std::vector<pollfd> watch{{listener.value, POLLIN, 0}};
        for (auto& [fd,c] : clients) {
            if (c.output.empty()) {
                auto end = c.input.find('\n');
                if ((end == std::string::npos ? c.input.size() : end) > maxLine) {
                    c.output = "ERR request too large\n";
                    c.closing = true;
                } else if (end != std::string::npos) {
                    try { c.output = route(c.input.substr(0,end), cluster); }
                    catch (const std::exception& e) { c.output = "ERR " + std::string(e.what()); }
                    c.output += '\n';
                    c.input.erase(0,end + 1);
                }
            }
            short events = c.output.empty() ? POLLIN : POLLOUT;
            watch.push_back({fd, events, 0});
        }
        int n = poll(watch.data(), watch.size(), 100);
        if (n < 0 && errno != EINTR) throw std::runtime_error("router poll failed");
        if (n <= 0) return;
        if (watch.front().revents & POLLIN) {
            int fd = accept(listener.value,nullptr,nullptr);
            if (fd >= 0) {
                if (clients.size() >= 128) close(fd);
                else { makeNonblocking(fd); clients.try_emplace(fd); }
            }
        }
        for (std::size_t i=1; i<watch.size(); ++i) {
            auto [fd, interest, events] = watch[i];
            if (!events) continue;
            Client& c = clients.at(fd);
            bool lost = events & (POLLERR | POLLNVAL);
            if (!lost && !c.output.empty()) {
                auto count = send(fd,c.output.data()+c.sent,c.output.size()-c.sent,0);
                if (count > 0) {
                    c.sent += static_cast<std::size_t>(count);
                    if (c.sent == c.output.size()) {
                        c.output.clear(); c.sent = 0; lost = c.closing;
                    }
                } else lost = count == 0 || (errno != EINTR && errno != EAGAIN && errno != EWOULDBLOCK);
            } else if (!lost) {
                char buf[4096];
                auto count = recv(fd,buf,sizeof(buf),0);
                if (count > 0) c.input.append(buf,static_cast<std::size_t>(count));
                else lost = count == 0 || (errno != EINTR && errno != EAGAIN && errno != EWOULDBLOCK);
            }
            if (lost) { close(fd); clients.erase(fd); }
        }
    }
};
// This operation requires local filesystem ownership, and is never routed from TCP.
int resizeLocal(std::string_view portText, std::string_view sizeText) {
    Bytes port, size;
    if (!parseNumber(portText, port) || port < firstPort || port >= firstPort + maxLocalNodes ||
        !parseNumber(sizeText, size) || !size)
        throw std::runtime_error("Usage: cluster-manager resize NODE_PORT NEW_BYTES");
    auto dir = fs::path("cluster-data") / ("node-" + std::to_string(port - firstPort + 1));
    auto file = dir / "capacity.bytes";
    if (!fs::exists(file)) throw std::runtime_error("no such managed node in this working directory");
    FD running(open("cluster-data/manager.lock", O_RDWR | O_CLOEXEC));
    if (running.value < 0 || flock(running.value, LOCK_EX | LOCK_NB) == 0 ||
        (errno != EWOULDBLOCK && errno != EAGAIN))
        throw std::runtime_error("no running manager in this directory");
    FD guard(open("cluster-data/resize.lock", O_RDWR | O_CREAT | O_CLOEXEC, 0600));
    if (guard.value < 0 || flock(guard.value, LOCK_EX)) throw std::runtime_error("cannot lock resize operation");
    auto current = stats(static_cast<int>(port));
    if (!current) throw std::runtime_error("node is unavailable");
    if (size < std::max(savedCapacity(file), current->max))
        throw std::runtime_error("only increases are supported");
    saveCapacity(file, size);
    auto reply = nodeRequest(static_cast<int>(port), "RELOADCAP");
    auto applied = stats(static_cast<int>(port));
    if (reply != "OK" || !applied || applied->max != size)
        throw std::runtime_error("budget saved; live change unconfirmed. Retry from the manager's directory");
    std::cout << "OK port=" << port << " max_bytes=" << size << '\n';
    return 0;
}
} // namespace

int main(int argc, char* argv[]) {
    if (argc == 4 && std::string_view(argv[1]) == "resize") {
        std::signal(SIGPIPE, SIG_IGN);
        try { return resizeLocal(argv[2], argv[3]); }
        catch (const std::exception& e) { std::cerr << "Resize: " << e.what() << '\n'; return 1; }
    }
    Bytes percent = 80, capacity = 4096, limit = 2;
    if (argc < 2 || argc > 5 ||
        (argc >= 3 && !parseNumber(argv[2], percent)) || percent < 1 || percent > 99 ||
        (argc >= 4 && !parseNumber(argv[3], capacity)) || capacity == 0 ||
        (argc == 5 && !parseNumber(argv[4], limit)) || limit == 0 || limit > maxLocalNodes) {
        std::cerr << "Usage: cluster-manager PATH_TO_FAST_KV [threshold_percent 1..99] [capacity_bytes > 0] [max_nodes 1..32]\n";
        return 1;
    }
    try {
        auto binary = fs::canonical(argv[1]);
        fs::create_directories("cluster-data");
        fs::permissions("cluster-data", fs::perms::owner_all);
        FD lock(open("cluster-data/manager.lock", O_RDWR | O_CREAT | O_CLOEXEC, 0600));
        if (lock.value < 0 || flock(lock.value, LOCK_EX | LOCK_NB))
            throw std::runtime_error("Cannot lock cluster-data; another manager may already be running");

        std::signal(SIGINT, requestStop);
        std::signal(SIGTERM, requestStop);
        std::signal(SIGPIPE, SIG_IGN);
        // Round up without overflowing capacity * percent.
        Bytes trigger = capacity / 100 * percent + (capacity % 100 * percent + 99) / 100;
        std::cout << "Scale at " << percent << "% (" << trigger << "/" << capacity << " bytes)" << std::endl;
        Cluster cluster{binary, capacity, static_cast<unsigned>(limit), {}};
        cluster.restore();
        if (!stopping) recoverMove(cluster);
        Router router;
        auto nextCheck = std::chrono::steady_clock::now();
        while (!stopping) {
            cluster.supervise();
            if (cluster.nodes.size() < cluster.limit && std::chrono::steady_clock::now() >= nextCheck) {
                nextCheck = std::chrono::steady_clock::now() + 200ms;
                // Add headroom only when every active node has crossed the threshold.
                bool full = std::all_of(cluster.nodes.begin(), cluster.nodes.end(),
                    [&](const auto& node) {
                        auto st = stats(node->port);
                        if (!st) return false;
                        Bytes localTrigger = st->max / 100 * percent + (st->max % 100 * percent + 99) / 100;
                        return st->used >= localTrigger;
                    });
                if (full) {
                    try { cluster.launch(); }
                    catch (const std::exception& e) {
                        std::cerr << "Scale-out deferred: " << e.what() << '\n';
                        nextCheck = std::chrono::steady_clock::now() + 5s;
                    }
                }
            }
            router.tick(cluster);
        }
    } catch (const std::exception& e) {
        std::cerr << "Manager: " << e.what() << '\n';
        return 1;
    }
}