#include "ui.h"
#include "pico/stdlib.h"
#include "board_config.h"

/* Cada padrao tem 20 passos de 50 ms (1 s); bit 0 primeiro, 1 = aceso. */
#define SLOT_MS 50u
#define SLOTS   20u

static const uint32_t patterns[] = {
    [LED_HEARTBEAT] = 0x00001u,     /* 50 ms aceso, 950 ms apagado */
    [LED_LINK]      = 0x00011u,     /* dois pulsos de 50 ms */
    [LED_ACTIVE]    = 0xFFFFCu,     /* aceso, apaga por 100 ms */
    [LED_FAULT]     = 0x33333u,     /* 100 ms aceso / 100 ms apagado */
};

static volatile uint8_t current = LED_HEARTBEAT;
static uint8_t slot, sub;

void led_init(void)
{
    gpio_init(LED_PIN);
    gpio_set_dir(LED_PIN, GPIO_OUT);
}

void led_set_pattern(led_pattern_t p)
{
    current = (uint8_t)p;
}

void led_tick(void)
{
    if (++sub < SLOT_MS / UI_SCAN_MS)
        return;
    sub = 0;
    gpio_put(LED_PIN, (patterns[current] >> slot) & 1u);
    if (++slot >= SLOTS)
        slot = 0;
}
