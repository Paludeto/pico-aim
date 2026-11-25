/* Aplicacao do core 0 (spec 6.6 e 6.7): dona do modo, da habilitacao e dos
 * parametros. Trata os pacotes do PC, o BOOTSEL e o estado do USB, e gera a
 * configuracao (ctrl_cmd_t) que vai para o core 1. Portavel: a flash entra
 * pela interface persist.h, entao compila no PC para os testes.
 */
#ifndef APP_H
#define APP_H
#include <stdint.h>
#include <stdbool.h>
#include "../proto/proto.h"

typedef enum { APP_BTN_SHORT = 0, APP_BTN_LONG = 1 } app_button_t;

typedef struct {
    uint8_t mode;           /* modo pedido pelo PC */
    uint8_t core_state;     /* estado informado pelo core 1 */
    bool enabled;           /* HABILITADO pelo BOOTSEL */
    bool usb_ok;
    bool link_ok;
    uint16_t errs;
} app_status_t;

/* Parametros padrao ou, se houver copia valida, os da flash. Sempre
 * comeca em DESLIGADO e desabilitado. */
void app_init(void);

/* Pacote valido do PC. Retorna true se *meas deve ir para o core 1.
 * Se *resp_len > 0, resp (>= PROTO_TX_MAX bytes) tem a resposta a enviar. */
bool app_on_frame(const proto_frame_t *f, ctrl_meas_t *meas, uint8_t *resp, uint8_t *resp_len);
void app_on_proto_error(void);              /* CRC ou LEN invalido */
void app_on_button(app_button_t b);         /* curta: alterna habilitacao; longa: emergencia */
void app_on_usb(bool ready);                /* montado e nao suspenso */
void app_on_telem(const ctrl_telem_t *t);

bool app_cmd_pending(void);
void app_take_cmd(ctrl_cmd_t *cmd);
void app_get_status(app_status_t *st);

#endif
