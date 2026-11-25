/* Botao BOOTSEL em tempo de execucao (tecnica do exemplo picoboard/button do
 * pico-examples). O botao puxa para GND o CS da flash QSPI; para le-lo e
 * preciso soltar o CS (saida em alta impedancia), esperar a linha estabilizar
 * e ler o pino. Enquanto isso a flash fica inacessivel, entao:
 *   - a funcao roda da RAM e com as interrupcoes do core 0 desligadas;
 *   - o core 1 nao pode tocar na flash: o firmware inteiro roda da RAM
 *     (copy_to_ram no CMakeLists.txt).
 */
#include "ui.h"
#include "pico/stdlib.h"
#include "hardware/sync.h"
#include "hardware/structs/ioqspi.h"
#include "hardware/structs/sio.h"
#include "board_config.h"

bool __no_inline_not_in_flash_func(bootsel_read)(void)
{
    const uint CS_PIN_INDEX = 1;
    uint32_t irq = save_and_disable_interrupts();

    hw_write_masked(&ioqspi_hw->io[CS_PIN_INDEX].ctrl,
                    GPIO_OVERRIDE_LOW << IO_QSPI_GPIO_QSPI_SS_CTRL_OEOVER_LSB,
                    IO_QSPI_GPIO_QSPI_SS_CTRL_OEOVER_BITS);
    for (volatile int i = 0; i < 1000; ++i)
        ;                                       /* nao da para chamar sleep (esta na flash no build padrao) */
    bool pressed = !(sio_hw->gpio_hi_in & (1u << CS_PIN_INDEX));
    hw_write_masked(&ioqspi_hw->io[CS_PIN_INDEX].ctrl,
                    GPIO_OVERRIDE_NORMAL << IO_QSPI_GPIO_QSPI_SS_CTRL_OEOVER_LSB,
                    IO_QSPI_GPIO_QSPI_SS_CTRL_OEOVER_BITS);

    restore_interrupts(irq);
    return pressed;
}

uint8_t bootsel_tick(void)
{
    static bool stable, long_fired;
    static uint8_t diff;
    static uint16_t held_ms;
    uint8_t ev = 0;

    bool raw = bootsel_read();
    if (raw == stable) {
        diff = 0;
    } else if (++diff >= BTN_DEBOUNCE_SCANS) {  /* debounce: N leituras iguais seguidas */
        diff = 0;
        stable = raw;
        if (stable) {
            held_ms = 0;
            long_fired = false;
        } else if (!long_fired) {
            ev |= BOOTSEL_EV_SHORT;
        }
    }
    if (stable && !long_fired) {
        held_ms += UI_SCAN_MS;
        if (held_ms >= BTN_LONG_MS) {
            long_fired = true;
            ev |= BOOTSEL_EV_LONG;
        }
    }
    return ev;
}
