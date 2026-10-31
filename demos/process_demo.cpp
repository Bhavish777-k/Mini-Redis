// Process management demo for Linux: fork() + exec + waitpid().

#include <sys/types.h>
#include <sys/wait.h>
#include <unistd.h>

#include <cerrno>
#include <cstring>
#include <iostream>

using namespace std;

int main() {
    cout << "Parent process ID: " << getpid() << '\n';
    cout.flush();

    // Create the child process
    pid_t child = fork();

    if (child < 0) {
        cout << "Process creation failed.\n";
        cout << "Error: " << strerror(errno) << '\n';
        return 1;
    }

    if (child == 0) {
        // Child: replace this process image with /bin/echo
        execlp(
            "echo",
            "echo",
            "Child process is running",
            static_cast<char*>(nullptr)
        );

        // Only reached if exec failed
        cerr << "exec failed: " << strerror(errno) << '\n';
        _exit(127);
    }

    cout << "Child process started.\n";
    cout << "Child process ID: " << child << '\n';
    cout.flush();

    // Wait for the child process to finish
    int status = 0;

    if (waitpid(child, &status, 0) < 0) {
        cout << "waitpid failed: " << strerror(errno) << '\n';
        return 1;
    }

    // Get the child's exit code
    int exitCode = WIFEXITED(status) ? WEXITSTATUS(status) : -1;

    cout << "Child process finished.\n";
    cout << "Exit code: " << exitCode << '\n';

    return 0;
}
