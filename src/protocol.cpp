
#include "protocol.h"

#include <algorithm>
#include <cctype>

std::vector<std::string> Protocol::parse(
    const std::string& input
) {
    std::vector<std::string> parts;
    std::string word;

    for (char ch : input) {
        if (std::isspace(static_cast<unsigned char>(ch))) {
            if (!word.empty()) {
                parts.push_back(word);
                word.clear();
            }
        } else {
            word += ch;
        }
    }

    if (!word.empty()) {
        parts.push_back(word);
    }

    // Commands are case-insensitive.
    if (!parts.empty()) {
        std::transform(
            parts[0].begin(),
            parts[0].end(),
            parts[0].begin(),
            [](unsigned char ch) {
                return static_cast<char>(std::toupper(ch));
            }
        );
    }

    return parts;
}

bool Protocol::isValid(
    const std::vector<std::string>& parts
) {
    if (parts.empty()) {
        return false;
    }

    const std::string& command = parts[0];

    if (command == "STATS" || command == "ALLOCSTATS" ||
        command == "PING" || command == "COUNT" ||
        command == "KEYS") {
        return parts.size() == 1;
    }

    if (command == "RELOADCAP") return parts.size() == 1;

    if (command == "SET") {
        return parts.size() == 3;
    }

    if (command == "GET" || command == "DEL" ||
        command == "EXISTS" || command == "INCR") {
        return parts.size() == 2;
    }

    return false;
}

std::string Protocol::makeResponse(
    const std::string& message
) {
    return message;
}
