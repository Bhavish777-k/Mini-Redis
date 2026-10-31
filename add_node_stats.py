from pathlib import Path

files = {}
def change(path, old, new):
    path = Path(path)
    s = files.get(path, path.read_text())
    if s.count(old) != 1:
        raise SystemExit(f"Stopped before saving: check {path} for {old!r}")
    files[path] = s.replace(old, new, 1)

change("include/kv_store.h", "    KVStore();", """    explicit KVStore(std::size_t maxBytes = 1024 * 1024);
    std::size_t usedBytes() const { return memoryManager_.usedBytes(); }
    std::size_t maxBytes() const { return memoryManager_.maxBytes(); }""")
change("include/kv_store.h", "memoryManager_{1024 * 1024}", "memoryManager_")
change("src/kv_store.cpp", "KVStore::KVStore() = default;", """KVStore::KVStore(std::size_t maxBytes)
    : memoryManager_(maxBytes) {}""")
change("src/protocol.cpp", 'command == "PING"', 'command == "STATS" || command == "PING"')
change("src/command.cpp", '    if (name == "COUNT") {', """    if (name == "STATS") {
        std::shared_lock<std::shared_mutex> lock(writeMutex_);
        return "used_bytes=" + std::to_string(store_.usedBytes()) +
               " max_bytes=" + std::to_string(store_.maxBytes()) +
               " keys=" + std::to_string(store_.count());
    }

    if (name == "COUNT") {""")
main = Path("src/main.cpp").read_text()
for header in ("charconv", "string_view"):
    if f"#include <{header}>" not in main:
        change("src/main.cpp", "#include <thread>", f"#include <{header}>\n#include <thread>")
start = main.index("int main(")
end = main.index("    unsigned int cores", start)
change("src/main.cpp", main[start:end], """namespace {
bool positiveNumber(std::string_view text, std::size_t& value) {
    const char* end = text.data() + text.size();
    auto parsed = std::from_chars(text.data(), end, value);
    return parsed.ec == std::errc{} && parsed.ptr == end && value > 0;
}
}

int main(int argc, char* argv[]) {
    std::size_t port = 6379;
    std::size_t maxBytes = 1024 * 1024;
    if (argc > 3 || (argc >= 2 && (!positiveNumber(argv[1], port) || port > 65535)) ||
        (argc == 3 && !positiveNumber(argv[2], maxBytes))) {
        std::cerr << "Usage: fast-kv [port 1..65535] [positive capacity in bytes]\\n";
        return 1;
    }

""")
change("src/main.cpp", "KVStore store;", "KVStore store(maxBytes);")
for path, source in files.items():
    path.write_text(source)
print("Updated node settings and STATS.")