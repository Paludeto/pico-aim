/* PID discreto em ponto fixo, portavel (sem dependencia de hardware).
 *
 * Ganhos em unidades "por amostra" (Q16.16):
 *   kp = Kp            [contagens/px]
 *   ki = Ki * T        [contagens/px por amostra]
 *   kd = Kd / T
 * Limites: 0 <= ganho < PID_GAIN_MAX e |e| <= PID_E_MAX, o que garante
 * que nenhum produto estoura int32_t (16 * 2047 * 65536 < 2^31; T = 1 ms).
 */
#ifndef PID_H
#define PID_H
#include <stdint.h>
#include <stdbool.h>
#include "fixed.h"

#define PID_GAIN_MAX  (Q16_FROM_INT(16) - 1)
#define PID_E_MAX     2047
#define PID_U_MAX     127
#define PID_D_SHIFT_MAX 8

typedef struct {
    q16_t kp, ki, kd;
    int16_t deadband;   /* px; |e| <= deadband => u = 0 */
    uint8_t d_shift;    /* passa-baixas da derivada: alfa = 2^-d_shift */
} pid_cfg_t;

typedef struct {
    q16_t integ;        /* termo integral ja multiplicado por ki */
    q16_t ef;           /* erro filtrado */
    q16_t resid;        /* residuo fracionario de u */
    bool primed;
    bool saturated;     /* ultimo passo saturou */
} pid_state_t;

void pid_reset(pid_state_t *s);
int8_t pid_step(pid_state_t *s, const pid_cfg_t *cfg, int16_t e);

#endif
