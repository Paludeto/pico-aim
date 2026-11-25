/* Rastreador visual de cursor com mouse HID emulado - firmware do RP2040.
 * Sistemas Microcontrolados, UTFPR Apucarana.
 *
 * Core 0 (este arquivo): dono exclusivo do TinyUSB. CDC RX -> parser ->
 * aplicacao; filas do core 1 -> relatorio HID e telemetria; BOOTSEL, LED e
 * watchdog. Core 1 (core1/core1.c): passo de controle a 1 kHz.
 */
#include "pico/stdlib.h"
#include "hardware/watchdog.h"
#include "hardware/sync.h"
#include "tusb.h"
#include "board_config.h"
#include "app/app.h"
#include "core1/core1.h"
#include "proto/proto.h"
#include "ui/ui.h"

#define LOAD_WINDOW_US 100000u

static proto_parser_t parser;
static int32_t pend_x, pend_y;      /* movimento ainda nao entregue ao host */
static uint16_t load0;              /* carga do core 0, por mil */

static int32_t clamp(int32_t v, int32_t lo, int32_t hi)
{
    return v < lo ? lo : (v > hi ? hi : v);
}

/* Respostas e telemetria: so com a porta aberta no PC (DTR) e sem bloquear.
 * Se nao couber no buffer de TX, o quadro e descartado. */
static void cdc_send(const uint8_t *buf, uint8_t len)
{
    if (tud_cdc_connected() && tud_cdc_write_available() >= len)
        tud_cdc_write(buf, len);
}

static void cdc_rx_task(void)
{
    uint8_t chunk[64], resp[PROTO_TX_MAX], resp_len;
    proto_frame_t f;
    ctrl_meas_t meas;

    while (tud_cdc_available()) {
        uint32_t n = tud_cdc_read(chunk, sizeof chunk);
        for (uint32_t i = 0; i < n; i++) {
            switch (proto_parser_feed(&parser, chunk[i], &f)) {
            case PROTO_FRAME:
                if (app_on_frame(&f, &meas, resp, &resp_len))
                    (void)core1_send_meas(&meas);
                if (resp_len)
                    cdc_send(resp, resp_len);
                break;
            case PROTO_BAD_CRC:
            case PROTO_BAD_LEN:
                app_on_proto_error();
                break;
            default:
                break;
            }
        }
    }
}

static void telem_task(void)
{
    uint8_t buf[PROTO_TX_MAX];
    ctrl_telem_t t;
    app_status_t st;

    while (core1_recv_telem(&t)) {
        app_on_telem(&t);
        app_get_status(&st);
        cdc_send(buf, proto_build_telem(buf, &t, st.errs, load0));
    }
    tud_cdc_write_flush();
}

/* Soma os comandos do core 1 e envia um relatorio quando o endpoint esta
 * livre. Se o host atrasar, nada se perde ate HID_PENDING_MAX. */
static void hid_task(void)
{
    ctrl_u_t u;
    while (core1_recv_u(&u)) {
        pend_x = clamp(pend_x + u.dx, -HID_PENDING_MAX, HID_PENDING_MAX);
        pend_y = clamp(pend_y + u.dy, -HID_PENDING_MAX, HID_PENDING_MAX);
    }
    if ((pend_x != 0 || pend_y != 0) && tud_hid_ready()) {
        int8_t dx = (int8_t)clamp(pend_x, -127, 127);
        int8_t dy = (int8_t)clamp(pend_y, -127, 127);
        if (tud_hid_mouse_report(0, 0, dx, dy, 0, 0)) {
            pend_x -= dx;
            pend_y -= dy;
            gpio_xor_mask(1u << DBG_PIN_HID);
        }
    }
}

static void usb_state_task(void)
{
    static bool last;
    bool ready = tud_mounted() && !tud_suspended();
    if (ready != last) {
        last = ready;
        app_on_usb(ready);
    }
    if (!ready)
        pend_x = pend_y = 0;
}

static void ui_task(void)
{
    uint8_t ev = ui_take_events();
    app_status_t st;

    if (ev & BOOTSEL_EV_LONG)
        app_on_button(APP_BTN_LONG);
    else if (ev & BOOTSEL_EV_SHORT)
        app_on_button(APP_BTN_SHORT);

    app_get_status(&st);
    if (!st.usb_ok || (st.mode != CTRL_OFF && !st.link_ok))
        led_set_pattern(LED_FAULT);
    else if (st.enabled)
        led_set_pattern(LED_ACTIVE);
    else if (st.link_ok)
        led_set_pattern(LED_LINK);
    else
        led_set_pattern(LED_HEARTBEAT);
}

/* Dorme ate a proxima interrupcao do core 0 (USB, timer de 10 ms) ou ate o
 * core 1 mexer numa fila (o unlock das filas faz SEV). O tempo dormindo da a
 * carga do core 0. */
static void idle(void)
{
    static uint32_t win_start, idle_us;
    uint32_t t0 = time_us_32();
    __wfe();
    uint32_t t1 = time_us_32();

    idle_us += t1 - t0;
    if (t1 - win_start >= LOAD_WINDOW_US) {
        uint32_t win = t1 - win_start;
        if (idle_us > win)
            idle_us = win;
        load0 = (uint16_t)(1000u - (uint32_t)((uint64_t)idle_us * 1000u / win));
        win_start = t1;
        idle_us = 0;
    }
}

int main(void)
{
    gpio_init(DBG_PIN_HID);
    gpio_set_dir(DBG_PIN_HID, GPIO_OUT);

    proto_parser_init(&parser);
    app_init();                     /* le a flash antes de existir o core 1 */
    ui_init();
    tusb_init();
    core1_start();
    watchdog_enable(WATCHDOG_MS, true);

    for (;;) {
        tud_task();
        usb_state_task();
        cdc_rx_task();
        ui_task();
        telem_task();

        /* Configuracao nova para o core 1. Fila cheia: fica pendente e tenta
         * na proxima volta (so o core 0 escreve nessa fila). */
        if (app_cmd_pending() && core1_cmd_ready()) {
            ctrl_cmd_t cmd;
            app_take_cmd(&cmd);
            (void)core1_send_cmd(&cmd);
        }

        hid_task();

        /* Watchdog: este laco girando prova o core 0; o contador de passos
         * andando prova o core 1. */
        if (core1_alive())
            watchdog_update();

        idle();
    }
}
