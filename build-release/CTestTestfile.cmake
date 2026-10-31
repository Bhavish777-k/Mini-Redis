# CMake generated Testfile for 
# Source directory: /Users/awnishkumar/Desktop/mini_redis
# Build directory: /Users/awnishkumar/Desktop/mini_redis/build-release
# 
# This file includes the relevant testing commands required for 
# testing this directory and lists subdirectories to be tested as well.
add_test("ProtocolTest" "/Users/awnishkumar/Desktop/mini_redis/build-release/test_protocol")
set_tests_properties("ProtocolTest" PROPERTIES  _BACKTRACE_TRIPLES "/Users/awnishkumar/Desktop/mini_redis/CMakeLists.txt;50;add_test;/Users/awnishkumar/Desktop/mini_redis/CMakeLists.txt;0;")
add_test("KVStoreTest" "/Users/awnishkumar/Desktop/mini_redis/build-release/test_kv_store")
set_tests_properties("KVStoreTest" PROPERTIES  _BACKTRACE_TRIPLES "/Users/awnishkumar/Desktop/mini_redis/CMakeLists.txt;57;add_test;/Users/awnishkumar/Desktop/mini_redis/CMakeLists.txt;0;")
add_test("ConcurrencyTest" "/Users/awnishkumar/Desktop/mini_redis/build-release/test_concurrency")
set_tests_properties("ConcurrencyTest" PROPERTIES  _BACKTRACE_TRIPLES "/Users/awnishkumar/Desktop/mini_redis/CMakeLists.txt;66;add_test;/Users/awnishkumar/Desktop/mini_redis/CMakeLists.txt;0;")
add_test("PersistenceTest" "/Users/awnishkumar/Desktop/mini_redis/build-release/test_persistence")
set_tests_properties("PersistenceTest" PROPERTIES  _BACKTRACE_TRIPLES "/Users/awnishkumar/Desktop/mini_redis/CMakeLists.txt;75;add_test;/Users/awnishkumar/Desktop/mini_redis/CMakeLists.txt;0;")
add_test("EvictionTest" "/Users/awnishkumar/Desktop/mini_redis/build-release/test_eviction")
set_tests_properties("EvictionTest" PROPERTIES  _BACKTRACE_TRIPLES "/Users/awnishkumar/Desktop/mini_redis/CMakeLists.txt;83;add_test;/Users/awnishkumar/Desktop/mini_redis/CMakeLists.txt;0;")
