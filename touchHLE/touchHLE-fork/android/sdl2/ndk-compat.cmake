set(CMAKE_SYSTEM_NAME Android)
set(CMAKE_SYSTEM_PROCESSOR aarch64)
add_link_options("-Wl,-z,max-page-size=16384")

# rust-sdl2 builds this SDL revision from Cargo's own checkout. Limit the
# NDK 27 API substitution to its one nonblocking sensor poll.
set_property(SOURCE "${CMAKE_CURRENT_SOURCE_DIR}/src/sensor/android/SDL_androidsensor.c"
    PROPERTY COMPILE_OPTIONS "-include" "${CMAKE_CURRENT_LIST_DIR}/sensor-looper.h")
