# Firmware do rastreador de cursor - Raspberry Pi Pico (RP2040), Pico SDK.
#   mkdir build && cd build && cmake .. && make      -> cursor_tracker.uf2
# Precisa de PICO_SDK_PATH (ou -DPICO_SDK_FETCH_FROM_GIT=ON).
cmake_minimum_required(VERSION 3.13)

set(PICO_BOARD pico CACHE STRING "Placa")
include(pico_sdk_import.cmake)

project(cursor_tracker C CXX ASM)
set(CMAKE_C_STANDARD 11)
set(CMAKE_C_STANDARD_REQUIRED ON)

pico_sdk_init()

add_executable(cursor_tracker
    src/main.c
    src/usb/usb_descriptors.c
    src/proto/proto.c
    src/proto/crc8.c
    src/ctrl/pid.c
    src/ctrl/estimator.c
    src/ctrl/params.c
    src/ctrl/loop.c
    src/core1/core1.c
    src/ui/led.c
    src/ui/bootsel.c
    src/ui/ui.c
    src/app/app.c
    src/app/persist.c
)

target_include_directories(cursor_tracker PRIVATE
    ${CMAKE_CURRENT_LIST_DIR}           # board_config.h
    ${CMAKE_CURRENT_LIST_DIR}/src/usb   # tusb_config.h
)

target_compile_options(cursor_tracker PRIVATE -Wall -Wextra)

target_link_libraries(cursor_tracker PRIVATE
    pico_stdlib
    pico_multicore
    pico_unique_id
    hardware_timer
    hardware_flash
    hardware_sync
    hardware_watchdog
    tinyusb_device
)

# O USB e do TinyUSB (CDC + HID proprios): sem stdio por USB nem por UART.
pico_enable_stdio_usb(cursor_tracker 0)
pico_enable_stdio_uart(cursor_tracker 0)

# O firmware inteiro e copiado para a RAM no boot. Assim o core 1 nunca
# executa da flash, e a leitura do BOOTSEL (que desliga o XIP por alguns us)
# e a gravacao dos parametros nao atrasam o passo de controle.
pico_set_binary_type(cursor_tracker copy_to_ram)

pico_add_extra_outputs(cursor_tracker)  # .uf2, .hex, .bin
