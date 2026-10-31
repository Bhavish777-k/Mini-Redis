
#include <arpa/inet.h>
#include <netinet/in.h>
#include <sys/socket.h>
#include <sys/types.h>
#include <unistd.h>

#include <chrono>
#include <cstdlib>
#include <iostream>
#include <string>

int main(int argc, char* argv[]) {
    const char* host = "127.0.0.1";
    const char* port = "6379";

    int requestCount = 10000;

    if (argc > 1) {
        requestCount = std::atoi(argv[1]);
    }

    if (requestCount <= 0) {
        std::cerr << "Request count must be positive.\n";
        return 1;
    }

    int client = socket(AF_INET, SOCK_STREAM, 0);

    if (client < 0) {
        std::cerr << "Socket creation failed.\n";
        return 1;
    }

    sockaddr_in address{};
    address.sin_family = AF_INET;
    address.sin_port = htons(6379);

    if (inet_pton(AF_INET, host, &address.sin_addr) != 1) {
        std::cerr << "Invalid server address.\n";
        close(client);
        return 1;
    }

    if (connect(
        client,
        reinterpret_cast<sockaddr*>(&address),
        sizeof(address)
    ) < 0) {
        std::cerr << "Could not connect to Fast-KV.\n";
        close(client);
        return 1;
    }

    std::string response;
    char buffer[4096];

    auto start = std::chrono::steady_clock::now();

    int completed = 0;

    for (int i = 0; i < requestCount; ++i) {
        std::string command =
            "SET key" + std::to_string(i) +
            " value" + std::to_string(i) + "\n";

        int sent = 0;

        while (sent < static_cast<int>(command.size())) {
            ssize_t result = send(
                client,
                command.data() + sent,
                command.size() - static_cast<std::size_t>(sent),
                MSG_NOSIGNAL
            );

            if (result <= 0) {
                std::cerr << "Send failed.\n";
                close(client);
                        return 1;
            }

            sent += static_cast<int>(result);
        }

        while (response.find('\n') == std::string::npos) {
            ssize_t received = recv(
                client,
                buffer,
                sizeof(buffer),
                0
            );

            if (received <= 0) {
                std::cerr << "Receive failed.\n";
                close(client);
                        return 1;
            }

            response.append(buffer, static_cast<std::size_t>(received));
        }

        std::size_t newline = response.find('\n');
        std::string result = response.substr(0, newline);
        response.erase(0, newline + 1);

        if (result != "OK") {
            std::cerr << "Unexpected response: "
                      << result << '\n';

            close(client);
                return 1;
        }

        ++completed;
    }

    auto end = std::chrono::steady_clock::now();

    double seconds =
        std::chrono::duration<double>(end - start).count();

    double throughput = completed / seconds;
    double averageLatencyMs =
        seconds * 1000.0 / completed;

    std::cout << "\nFast-KV Benchmark\n";
    std::cout << "-----------------\n";
    std::cout << "Requests completed: " << completed << '\n';
    std::cout << "Time taken: " << seconds << " seconds\n";
    std::cout << "Throughput: " << throughput
              << " requests/second\n";
    std::cout << "Average latency: " << averageLatencyMs
              << " ms/request\n";

    close(client);

    return 0;
}
