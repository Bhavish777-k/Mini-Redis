
cmake_minimum_required(VERSION 3.20)

project(fast-kv LANGUAGES CXX)

# Default to an optimized build when no build type is given
if(NOT CMAKE_BUILD_TYPE AND NOT CMAKE_CONFIGURATION_TYPES)
    set(CMAKE_BUILD_TYPE Release CACHE STRING "Build type" FORCE)
endif()

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

include_directories(include)

find_package(Threads REQUIRED)

# Main server
add_executable(fast-kv
    src/main.cpp
    src/server.cpp
    src/event_loop.cpp
    src/protocol.cpp
    src/command.cpp
    src/kv_store.cpp
    src/thread_pool.cpp
    src/persistence.cpp
    src/memory_manager.cpp
    src/slab_allocator.cpp
    src/metrics.cpp
)

target_link_libraries(fast-kv PRIVATE Threads::Threads)

# Compiler warnings
target_compile_options(fast-kv PRIVATE
    -Wall
    -Wextra
    -Wpedantic
)

# Cluster supervisor/router. POSIX process APIs (fork, waitpid, flock, poll).
if(UNIX)
    add_executable(cluster-manager cluster/manager.cpp)
    target_link_libraries(cluster-manager PRIVATE Threads::Threads)
    target_compile_options(cluster-manager PRIVATE -Wall -Wextra -Wpedantic)
endif()

# Unit tests
enable_testing()

add_executable(test_protocol
    tests/test_protocol.cpp
    src/protocol.cpp
)
target_include_directories(test_protocol PRIVATE include)
add_test(NAME ProtocolTest COMMAND test_protocol)

add_executable(test_kv_store
    tests/test_kv_store.cpp
    src/kv_store.cpp
)
target_include_directories(test_kv_store PRIVATE include)
add_test(NAME KVStoreTest COMMAND test_kv_store)

add_executable(test_concurrency
    tests/test_concurrency.cpp
    src/kv_store.cpp
    src/thread_pool.cpp
)
target_include_directories(test_concurrency PRIVATE include)
target_link_libraries(test_concurrency PRIVATE Threads::Threads)
add_test(NAME ConcurrencyTest COMMAND test_concurrency)

add_executable(test_persistence
    tests/test_persistence.cpp
    src/persistence.cpp
    src/kv_store.cpp
    src/protocol.cpp
)
target_include_directories(test_persistence PRIVATE include)
add_test(NAME PersistenceTest COMMAND test_persistence)

add_executable(test_eviction
    tests/test_eviction.cpp
    src/kv_store.cpp
    src/memory_manager.cpp
)
target_include_directories(test_eviction PRIVATE include)
add_test(NAME EvictionTest COMMAND test_eviction)

# OS and synchronization demos
add_executable(process_demo demos/process_demo.cpp)
add_executable(race_demo demos/race_demo.cpp)
add_executable(deadlock_demo demos/deadlock_demo.cpp)

# Benchmark client
add_executable(benchmark_client benchmarks/benchmark_client.cpp)
target_link_libraries(benchmark_client PRIVATE Threads::Threads)

target_sources(test_kv_store PRIVATE src/memory_manager.cpp)
target_sources(test_concurrency PRIVATE src/memory_manager.cpp)
target_sources(test_persistence PRIVATE src/memory_manager.cpp)
# OS memory-allocation experiments (a real PMR resource used by KVStore values).
foreach(target test_kv_store test_concurrency test_persistence test_eviction)
    target_sources(${target} PRIVATE src/slab_allocator.cpp)
endforeach()

add_executable(test_slab_allocator tests/test_slab_allocator.cpp
    src/slab_allocator.cpp src/kv_store.cpp src/memory_manager.cpp)
target_link_libraries(test_slab_allocator PRIVATE Threads::Threads)
add_test(NAME SlabAllocatorTest COMMAND test_slab_allocator)
