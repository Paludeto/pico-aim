#include "pid.h"

#define TERM_MAX Q16_FROM_INT(1024)
#define U_MAX_Q  Q16_FROM_INT(PID_U_MAX)

void pid_reset(pid_state_t *s)
{
    s->integ = 0;
    s->ef = 0;
    s->resid = 0;
    s->primed = false;
    s->saturated = false;
}

int8_t pid_step(pid_state_t *s, const pid_cfg_t *cfg, int16_t e)
{
    e = clamp_i16(e, -PID_E_MAX, PID_E_MAX);
    q16_t e_q = Q16_FROM_INT(e);

    /* derivada filtrada: e_f[k] = e_f[k-1] + (e - e_f[k-1]) * 2^-n */
    if (!s->primed) {
        s->ef = e_q;
        s->primed = true;
    }
    q16_t ef_prev = s->ef;
    s->ef += (e_q - s->ef) >> cfg->d_shift;

    /* zona morta: para de mexer, descarta o residuo, congela o integrador */
    int16_t ae = e < 0 ? (int16_t)-e : e;
    if (ae <= cfg->deadband) {
        s->resid = 0;
        s->saturated = false;
        return 0;
    }

    q16_t p = clamp_i32(cfg->kp * (int32_t)e, -TERM_MAX, TERM_MAX);

    /* diferenca em Q8.8 (limitada) x kd em Q8.8 -> Q16.16 */
    int32_t dq8 = clamp_i32((s->ef - ef_prev) >> 8, -32767, 32767);
    q16_t d = clamp_i32((cfg->kd >> 8) * dq8, -TERM_MAX, TERM_MAX);

    /* incremento limitado antes da soma, para a soma nao estourar int32_t */
    q16_t i_inc = clamp_i32(cfg->ki * (int32_t)e, -2 * U_MAX_Q, 2 * U_MAX_Q);
    q16_t i_new = clamp_i32(s->integ + i_inc, -U_MAX_Q, U_MAX_Q);

    q16_t u = p + i_new + d + s->resid;
    int16_t ui = q16_trunc(u);

    if (ui > PID_U_MAX || ui < -PID_U_MAX) {
        bool pos = ui > 0;
        ui = pos ? PID_U_MAX : -PID_U_MAX;
        s->resid = 0;
        s->saturated = true;
        /* anti-windup (clamping): so integra se for para sair da saturacao */
        if ((pos && e < 0) || (!pos && e > 0))
            s->integ = i_new;
    } else {
        s->integ = i_new;
        s->resid = u - Q16_FROM_INT(ui);
        s->saturated = false;
    }
    return (int8_t)ui;
}
