/* Ponto fixo Q16.16 (int32_t). Sem float em tempo de execucao.
 * Q16_CONST() usa double apenas em constantes, resolvidas pelo compilador. */
#ifndef FIXED_H
#define FIXED_H
#include <stdint.h>

typedef int32_t q16_t;

#define Q16_SHIFT 16
#define Q16_ONE   ((q16_t)1 << Q16_SHIFT)
#define Q16_CONST(x) ((q16_t)((x) * 65536.0 + ((x) >= 0 ? 0.5 : -0.5)))
#define Q16_FROM_INT(i) ((q16_t)(i) * Q16_ONE)

static inline int32_t clamp_i32(int32_t v, int32_t lo, int32_t hi)
{
    return v < lo ? lo : (v > hi ? hi : v);
}

static inline int16_t clamp_i16(int16_t v, int16_t lo, int16_t hi)
{
    return v < lo ? lo : (v > hi ? hi : v);
}

/* Parte inteira truncada em direcao a zero (o residuo mantem o sinal). */
static inline int16_t q16_trunc(q16_t v)
{
    return v >= 0 ? (int16_t)(v >> Q16_SHIFT) : (int16_t)(-((-v) >> Q16_SHIFT));
}

#endif
