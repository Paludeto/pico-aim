#include "estimator.h"

#define E_Q8_MAX ((int32_t)32767 * 256)

/* Satura em vez de estourar: sem medicoes novas (ex.: identificacao sem o
 * tracker rodando) o acumulador so anda em uma direcao. */
static int32_t sat_q8(int32_t v)
{
    return v > E_Q8_MAX ? E_Q8_MAX : (v < -E_Q8_MAX ? -E_Q8_MAX : v);
}

void est_reset(est_t *s)
{
    for (uint8_t i = 0; i < EST_HIST_LEN; i++)
        s->hist[i] = 0;
    s->head = 0;
    s->e_q8 = 0;
}

void est_measure(est_t *s, int16_t e_m, uint8_t latency_steps)
{
    int32_t e = (int32_t)e_m * 256;
    if (s->enabled) {
        if (latency_steps > EST_L_MAX)
            latency_steps = EST_L_MAX;
        int16_t sum = 0;
        uint8_t idx = s->head;
        while (latency_steps--) {
            idx = (uint8_t)((idx - 1u) & (EST_HIST_LEN - 1u));
            sum += s->hist[idx];
        }
        e -= (int32_t)s->gain_q8 * sum;
    }
    s->e_q8 = sat_q8(e);
}

void est_apply(est_t *s, int8_t u)
{
    s->hist[s->head] = u;
    s->head = (uint8_t)((s->head + 1u) & (EST_HIST_LEN - 1u));
    if (s->enabled)
        s->e_q8 = sat_q8(s->e_q8 - (int32_t)s->gain_q8 * u);
}

int16_t est_get(const est_t *s)
{
    int32_t v = s->e_q8 + 128;      /* arredonda */
    v >>= 8;
    if (v > 32767) v = 32767;
    if (v < -32768) v = -32768;
    return (int16_t)v;
}
