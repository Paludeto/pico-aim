/* Interface local: LED onboard (padroes de piscada) e botao BOOTSEL.
 * Um timer periodico de 10 ms no core 0 faz a varredura (spec 6.4). */
#ifndef UI_H
#define UI_H
#include <stdint.h>
#include <stdbool.h>

/* ---- led.c ---- */
typedef enum {
    LED_HEARTBEAT = 0,  /* 1 pulso curto por segundo: vivo, sem link */
    LED_LINK,           /* 2 pulsos curtos por segundo: link ativo, saida desabilitada */
    LED_ACTIVE,         /* aceso, com 1 apagada curta por segundo: HABILITADO */
    LED_FAULT           /* 5 Hz: failsafe (link perdido fora de DESLIGADO) ou USB fora */
} led_pattern_t;

void led_init(void);
void led_set_pattern(led_pattern_t p);
void led_tick(void);                    /* a cada UI_SCAN_MS */

/* ---- bootsel.c ---- */
#define BOOTSEL_EV_SHORT 0x01           /* soltou antes de BTN_LONG_MS */
#define BOOTSEL_EV_LONG  0x02           /* segurou por BTN_LONG_MS (dispara ainda pressionado) */

bool bootsel_read(void);                /* leitura crua; ~dezenas de us com IRQs do core 0 desligadas */
uint8_t bootsel_tick(void);             /* a cada UI_SCAN_MS; devolve BOOTSEL_EV_* */

/* ---- ui.c ---- */
void ui_init(void);                     /* inicia LED e o timer de varredura */
uint8_t ui_take_events(void);           /* eventos do BOOTSEL acumulados desde a ultima chamada */

#endif
