/* Passo de controle (spec 6.3, 6.6, 6.7): estimador + PID nos dois eixos,
 * modo de identificacao e failsafe de link. Portavel: nao toca em hardware,
 * recebe e devolve mensagens. No RP2040 roda no core 1 (core1/core1.c), dentro
 * da IRQ do alarme de 1 kHz; no PC roda nos testes.
 */
#ifndef CTRL_LOOP_H
#define CTRL_LOOP_H
#include <stdint.h>
#include <stdbool.h>
#include "params.h"
#include "pid.h"
#include "estimator.h"

#define CTRL_HZ                 1000u
#define CTRL_LINK_TIMEOUT_STEPS 100u    /* 100 ms sem MEAS valido => failsafe */
#define CTRL_TELEM_DIV          5u      /* telemetria a 200 Hz */

typedef enum { CTRL_OFF = 0, CTRL_AUTO = 1, CTRL_IDENT = 2, CTRL_NSTATES } ctrl_state_t;

/* flags de ctrl_meas_t (iguais ao campo FLAGS do pacote MEAS) */
#define CTRL_MEAS_VALID   0x01

/* flags de ctrl_telem_t */
#define CTRL_FL_ENABLED    0x01
#define CTRL_FL_LINK_OK    0x02
#define CTRL_FL_TARGET     0x04
#define CTRL_FL_EST_ON     0x08
#define CTRL_FL_IDENT_DONE 0x10         /* identificacao terminou; fica ate o modo mudar */
#define CTRL_FL_SATURATED  0x20

/* core 0 -> core 1: configuracao completa, aplicada de forma atomica no
 * inicio de um passo. */
typedef struct {
    ctrl_params_t params;
    uint8_t mode;               /* ctrl_state_t pedido */
    bool enable;                /* HABILITADO pelo BOOTSEL */
} ctrl_cmd_t;

/* core 0 -> core 1: medicao */
typedef struct {
    uint8_t flags;
    int16_t ex, ey;
} ctrl_meas_t;

/* core 1 -> core 0: comando de movimento de um passo */
typedef struct {
    int8_t dx, dy;
} ctrl_u_t;

/* core 1 -> core 0: telemetria */
typedef struct {
    uint32_t t_us;              /* preenchido pela cola do core 1 */
    uint16_t tick;              /* contador de passos */
    uint8_t state;
    uint8_t flags;
    int16_t em_x, em_y;         /* ultima medicao */
    int16_t eh_x, eh_y;         /* erro estimado */
    int16_t u_x, u_y;           /* soma dos comandos desde o quadro anterior */
    uint8_t hid_drop;           /* comandos descartados (fila u cheia) */
    uint8_t meas_age;           /* passos desde a ultima medicao */
    uint16_t load1;             /* carga do core 1, por mil (cola do core 1) */
} ctrl_telem_t;

typedef struct {
    ctrl_params_t p;
    pid_cfg_t cfg;
    uint8_t state;
    bool enabled, ident_done;
    bool link_ok, target_valid;
    uint8_t link_cnt, meas_age;
    uint16_t tick;
    int16_t em_x, em_y;
    est_t est[2];
    pid_state_t pid[2];
    uint16_t id_n;
    uint8_t lfsr;
    int8_t id_chip;
    uint8_t hid_drop;
    int16_t usum_x, usum_y;
    uint8_t telem_div;
} ctrl_loop_t;

#define CTRL_OUT_U     0x01     /* *u tem movimento a enviar */
#define CTRL_OUT_TELEM 0x02     /* *telem foi preenchido */

void ctrl_loop_init(ctrl_loop_t *c);
/* Um passo de 1 ms. cmd/meas: NULL se nao chegou nada. out_ready: ha espaco
 * para entregar u (senao u = 0 e o descarte e contado). */
unsigned ctrl_loop_step(ctrl_loop_t *c, const ctrl_cmd_t *cmd, const ctrl_meas_t *meas,
                        bool out_ready, ctrl_u_t *u, ctrl_telem_t *telem);

#endif
