#ifndef PROTOCOL_H
#define PROTOCOL_H

#include <string>
#include <vector>

class Protocol {
public:
    // Split a command into parts
    static std::vector<std::string> parse(
        const std::string& input
    );

    // Check whether a command is valid
    static bool isValid(
        const std::vector<std::string>& parts
    );

    // Build a response
    static std::string makeResponse(
        const std::string& message
    );
};

#endif
