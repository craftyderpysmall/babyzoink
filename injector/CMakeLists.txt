add_executable(gdbot-launch main.cpp)
target_link_libraries(gdbot-launch PRIVATE ole32 oleaut32)
target_compile_definitions(gdbot-launch PRIVATE WIN32_LEAN_AND_MEAN NOMINMAX UNICODE _UNICODE)
target_compile_options(gdbot-launch PRIVATE /W4 /permissive- /utf-8)
# Put the launcher next to gdbot_bridge.dll so its default --dll lookup works.
set_target_properties(gdbot-launch PROPERTIES
  RUNTIME_OUTPUT_DIRECTORY $<TARGET_FILE_DIR:gdbot_bridge>)
