# Localiza o Pico SDK. Versao reduzida do pico_sdk_import.cmake oficial
# (pico-sdk/external/pico_sdk_import.cmake); pode ser substituida por ele.
#
#   PICO_SDK_PATH            caminho de um clone do pico-sdk (variavel de ambiente ou -D)
#   PICO_SDK_FETCH_FROM_GIT  ON para baixar o SDK na pasta de build

if (DEFINED ENV{PICO_SDK_PATH} AND (NOT PICO_SDK_PATH))
    set(PICO_SDK_PATH $ENV{PICO_SDK_PATH})
    message("PICO_SDK_PATH do ambiente: ${PICO_SDK_PATH}")
endif ()

if (DEFINED ENV{PICO_SDK_FETCH_FROM_GIT} AND (NOT PICO_SDK_FETCH_FROM_GIT))
    set(PICO_SDK_FETCH_FROM_GIT $ENV{PICO_SDK_FETCH_FROM_GIT})
endif ()

set(PICO_SDK_PATH "${PICO_SDK_PATH}" CACHE PATH "Caminho do Raspberry Pi Pico SDK")
set(PICO_SDK_FETCH_FROM_GIT "${PICO_SDK_FETCH_FROM_GIT}" CACHE BOOL "Baixar o SDK do git se nao for encontrado")

if (NOT PICO_SDK_PATH)
    if (PICO_SDK_FETCH_FROM_GIT)
        include(FetchContent)
        FetchContent_Declare(
            pico_sdk
            GIT_REPOSITORY https://github.com/raspberrypi/pico-sdk
            GIT_TAG master
            GIT_SUBMODULES_RECURSE FALSE
        )
        message("Baixando o Pico SDK")
        FetchContent_Populate(pico_sdk)
        set(PICO_SDK_PATH ${pico_sdk_SOURCE_DIR})
        # O TinyUSB e um submodulo do SDK e e necessario aqui.
        execute_process(COMMAND git submodule update --init lib/tinyusb
                        WORKING_DIRECTORY ${PICO_SDK_PATH})
    else ()
        message(FATAL_ERROR
            "Pico SDK nao encontrado. Defina PICO_SDK_PATH ou use -DPICO_SDK_FETCH_FROM_GIT=ON.")
    endif ()
endif ()

get_filename_component(PICO_SDK_PATH "${PICO_SDK_PATH}" REALPATH BASE_DIR "${CMAKE_BINARY_DIR}")
if (NOT EXISTS ${PICO_SDK_PATH})
    message(FATAL_ERROR "A pasta '${PICO_SDK_PATH}' nao existe")
endif ()

set(PICO_SDK_INIT_CMAKE_FILE ${PICO_SDK_PATH}/pico_sdk_init.cmake)
if (NOT EXISTS ${PICO_SDK_INIT_CMAKE_FILE})
    message(FATAL_ERROR "A pasta '${PICO_SDK_PATH}' nao parece conter o Raspberry Pi Pico SDK")
endif ()

set(PICO_SDK_PATH ${PICO_SDK_PATH} CACHE PATH "Caminho do Raspberry Pi Pico SDK" FORCE)

include(${PICO_SDK_INIT_CMAKE_FILE})
