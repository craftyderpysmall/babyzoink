cmake_minimum_required(VERSION 3.24)
project(gdbot_bridge LANGUAGES C CXX)

if(NOT CMAKE_SIZEOF_VOID_P EQUAL 8)
  message(FATAL_ERROR "GD 2.2091 is x64: configure with -A x64")
endif()

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
# /MD release CRT: our std::string must match libcocos2d's layout and share the UCRT heap.
set(CMAKE_MSVC_RUNTIME_LIBRARY "MultiThreadedDLL")
if(NOT CMAKE_BUILD_TYPE AND NOT CMAKE_CONFIGURATION_TYPES)
  set(CMAKE_BUILD_TYPE Release)
endif()

include(FetchContent)
# Pinned to tag v1.3.4; sources compiled directly rather than via MinHook's own CMake.
FetchContent_Declare(minhook_src
  URL https://github.com/TsudaKageyu/minhook/archive/refs/tags/v1.3.4.tar.gz
  URL_HASH SHA256=1aebeae4ca898330c507860acc2fca2eb335fe446a3a2b8444c3bf8b2660a14e  # #44: pinned
  SOURCE_SUBDIR do-not-add-minhook-cmake  # download only; don't run MinHook's CMakeLists
)
FetchContent_MakeAvailable(minhook_src)
FetchContent_Declare(nlohmann_json
  URL https://github.com/nlohmann/json/releases/download/v3.11.3/json.tar.xz
  URL_HASH SHA256=d6c65aca6b1ed68e7a182f4757257b107ae403032760ed6ef121c9d55e81757d  # #44: pinned (= upstream release hash)
)
FetchContent_MakeAvailable(nlohmann_json)
add_library(minhook STATIC
  ${minhook_src_SOURCE_DIR}/src/buffer.c
  ${minhook_src_SOURCE_DIR}/src/hook.c
  ${minhook_src_SOURCE_DIR}/src/trampoline.c
  ${minhook_src_SOURCE_DIR}/src/hde/hde64.c
)
target_include_directories(minhook PUBLIC ${minhook_src_SOURCE_DIR}/include)

add_library(gdbot_bridge SHARED
  src/main.cpp
  src/isolation.cpp
  src/hooks.cpp
  src/control.cpp
  src/view.cpp
  src/cbf.cpp
  src/sha256.cpp
)
target_link_libraries(gdbot_bridge PRIVATE minhook nlohmann_json::nlohmann_json advapi32)
target_compile_definitions(gdbot_bridge PRIVATE WIN32_LEAN_AND_MEAN NOMINMAX UNICODE _UNICODE _CRT_SECURE_NO_WARNINGS)
target_compile_options(gdbot_bridge PRIVATE /W4 /permissive- /utf-8)

add_subdirectory(${CMAKE_CURRENT_SOURCE_DIR}/../injector ${CMAKE_CURRENT_BINARY_DIR}/injector)
