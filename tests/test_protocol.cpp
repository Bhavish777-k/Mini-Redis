
#include "protocol.h"

#include <cassert>
#include <iostream>
#include <string>
#include <vector>

void testParse() {
    std::vector<std::string> parts =
        Protocol::parse("SET name Rahul");

    assert(parts.size() == 3);
    assert(parts[0] == "SET");
    assert(parts[1] == "name");
    assert(parts[2] == "Rahul");

    std::cout << "Parse test passed.\n";
}

void testLowercaseCommand() {
    std::vector<std::string> parts =
        Protocol::parse("get name");

    assert(parts.size() == 2);
    assert(parts[0] == "GET");
    assert(parts[1] == "name");

    std::cout << "Lowercase command test passed.\n";
}

void testValidCommands() {
    assert(Protocol::isValid(
        Protocol::parse("PING")
    ));

    assert(Protocol::isValid(
        Protocol::parse("SET name Rahul")
    ));

    assert(Protocol::isValid(
        Protocol::parse("GET name")
    ));

    assert(Protocol::isValid(
        Protocol::parse("DEL name")
    ));

    std::cout << "Valid command tests passed.\n";
}

void testInvalidCommands() {
    assert(!Protocol::isValid(
        Protocol::parse("SET name")
    ));

    assert(!Protocol::isValid(
        Protocol::parse("GET")
    ));

    assert(!Protocol::isValid(
        Protocol::parse("UNKNOWN name")
    ));

    assert(!Protocol::isValid(
        Protocol::parse("")
    ));

    std::cout << "Invalid command tests passed.\n";
}

int main() {
    testParse();
    testLowercaseCommand();
    testValidCommands();
    testInvalidCommands();

    std::cout << "All protocol tests passed.\n";
    return 0;
}
