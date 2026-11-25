#include "ui.h"
#include "pico/stdlib.h"
#include "hardware/sync.h"
#include "board_config.h"

static repeating_timer_t scan_timer;
static volatile uint8_t events;

/* IRQ do alarm pool padrao (core 0), a cada 10 ms. Curta: uma leitura do
 * BOOTSEL e um gpio_put. */
static bool scan_cb(repeating_timer_t *t)
{
    (void)t;
    events |= bootsel_tick();
    led_tick();
    return true;
}

void ui_init(void)
{
    led_init();
    /* periodo negativo: intervalo entre inicios, sem acumular atraso */
    add_repeating_timer_ms(-(int32_t)UI_SCAN_MS, scan_cb, NULL, &scan_timer);
}

uint8_t ui_take_events(void)
{
    uint32_t irq = save_and_disable_interrupts();
    uint8_t ev = events;
    events = 0;
    restore_interrupts(irq);
    return ev;
}
