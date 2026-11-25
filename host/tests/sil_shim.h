#ifndef SIL_SHIM_H
#define SIL_SHIM_H
#include <stdint.h>
void sil_init(void);                    /* "boot": aplicacao + passo de controle; USB montado */
void sil_feed(uint8_t byte);            /* byte recebido pelo CDC */
int sil_step(int8_t *dx, int8_t *dy);   /* um passo de 1 ms; retorna 1 se houve movimento */
int sil_read(uint8_t *buf, int max);    /* bytes enviados pelo CDC (telemetria, ACK, PARAMS) */
void sil_button(int long_press);        /* BOOTSEL: 0 = pressao curta, 1 = longa */
void sil_set_usb(int ready);
void sil_set_hid_full(int full);        /* fila u cheia */
void sil_persist_clear(void);           /* apaga a "flash" */
#endif
