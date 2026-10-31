#include <cerrno>
#include <chrono>
#include <csignal>
#include <cstdio>
#include <filesystem>
#include <iostream>
#include <sys/wait.h>
#include <thread>
#include <unistd.h>

volatile std::sig_atomic_t stopping = 0;

void requestStop(int) {
    stopping = 1;
}

int main(int argc, char* argv[]) {
    if (argc != 2) {
        std::cerr << "Usage: cluster-manager PATH_TO_FAST_KV\n";
        return 1;
    }

    auto binary = std::filesystem::absolute(argv[1]);
    std::filesystem::path dataDir = "cluster-data/node-1";
    std::filesystem::create_directories(dataDir);

    std::signal(SIGINT, requestStop);
    std::signal(SIGTERM, requestStop);

    pid_t pid = fork();
    if (pid < 0) {
        std::perror("fork");
        return 1;
    }

    if (pid == 0) {
        // The child uses its own folder for its persistence log.
        if (chdir(dataDir.c_str()) < 0) {
            std::perror("chdir");
            _exit(1);
        }

        // Replace the child process with the existing Fast-KV server.
        execl(binary.c_str(), "fast-kv", "6381", "4096",
              static_cast<char*>(nullptr));

        std::perror("exec fast-kv");
        _exit(1);
    }

    // The parent stays alive as the cluster manager.
    std::cout << "Starting node-1, PID " << pid
              << ", port 6381\n" << std::flush;

    int status = 0;
    bool stopSent = false;

    while (true) {
        pid_t result = waitpid(pid, &status, WNOHANG);
        if (result == pid) break;

        if (result < 0 && errno != EINTR) {
            std::perror("waitpid");
            return 1;
        }

        if (stopping && !stopSent) {
            kill(pid, SIGTERM);
            stopSent = true;
        }

        std::this_thread::sleep_for(std::chrono::milliseconds(50));
    }

    return WIFEXITED(status) ? WEXITSTATUS(status) : 1;
}
