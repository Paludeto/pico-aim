/* Adaptacao do firmware para testes unitarios no PC: conecta app.c ao passo de
 * controle (ctrl/loop.c) sem depender do hardware do RP2040, mantendo a flash em RAM. */
#include <string.h>
#include "sil_shim.h"
#include "../../firmware/src/app/app.h"
#include "../../firmware/src/app/persist.h"

static proto_parser_t parser;
static ctrl_loop_t loop;
static ctrl_meas_t meas;
static int has_meas;
static int hid_full;
static uint8_t tx[16384];
static int tx_len;

static ctrl_params_t flash;
static int flash_valid;

bool persist_save(const ctrl_params_t *p) { flash = *p; flash_valid = 1; return true; }
bool persist_load(ctrl_params_t *p) { if (flash_valid) *p = flash; return flash_valid != 0; }
void sil_persist_clear(void) { flash_valid = 0; }

static void tx_put(const uint8_t *buf, int n)
{
    if (tx_len + n <= (int)sizeof tx) {
        memcpy(tx + tx_len, buf, (size_t)n);
        tx_len += n;
    }
}

void sil_init(void)
{
    proto_parser_init(&parser);
    app_init();
    ctrl_loop_init(&loop);
    app_on_usb(true);
    has_meas = 0;
    hid_full = 0;
    tx_len = 0;
}

void sil_feed(uint8_t byte)
{
    proto_frame_t f;
    uint8_t resp[PROTO_TX_MAX], resp_len;
    switch (proto_parser_feed(&parser, byte, &f)) {
    case PROTO_FRAME:
        if (app_on_frame(&f, &meas, resp, &resp_len))
            has_meas = 1;
        if (resp_len)
            tx_put(resp, resp_len);
        break;
    case PROTO_BAD_CRC:
    case PROTO_BAD_LEN:
        app_on_proto_error();
        break;
    default:
        break;
    }
}

int sil_step(int8_t *dx, int8_t *dy)
{
    ctrl_cmd_t cmd;
    ctrl_u_t u;
    ctrl_telem_t t;
    int has_cmd = app_cmd_pending();
    if (has_cmd)
        app_take_cmd(&cmd);
    unsigned out = ctrl_loop_step(&loop, has_cmd ? &cmd : NULL, has_meas ? &meas : NULL,
                                  !hid_full, &u, &t);
    has_meas = 0;
    if (out & CTRL_OUT_TELEM) {
        uint8_t buf[PROTO_TX_MAX];
        app_status_t st;
        t.t_us = (uint32_t)t.tick * 1000u;
        app_on_telem(&t);
        app_get_status(&st);
        tx_put(buf, proto_build_telem(buf, &t, st.errs, 0));
    }
    *dx = u.dx;
    *dy = u.dy;
    return (out & CTRL_OUT_U) != 0;
}

int sil_read(uint8_t *buf, int max)
{
    int n = tx_len < max ? tx_len : max;
    memcpy(buf, tx, (size_t)n);
    memmove(tx, tx + n, (size_t)(tx_len - n));
    tx_len -= n;
    return n;
}

void sil_button(int long_press) { app_on_button(long_press ? APP_BTN_LONG : APP_BTN_SHORT); }
void sil_set_usb(int ready) { app_on_usb(ready != 0); }
void sil_set_hid_full(int full) { hid_full = full; }
