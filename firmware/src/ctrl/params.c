#include "params.h"
#include "pid.h"
#include "estimator.h"

#define PLANT_GAIN_MIN (Q16_ONE / 8)
#define PLANT_GAIN_MAX (8 * Q16_ONE)

void params_defaults(ctrl_params_t *p)
{
    p->kp = Q16_CONST(0.06);
    p->ki = 0;
    p->kd = 0;
    p->plant_gain = Q16_ONE;
    p->latency = 30;
    p->deadband = 1;
    p->d_shift = 3;
    p->id_amp = 1;
    p->est_en = true;
}

static bool in_range(int32_t v, int32_t lo, int32_t hi)
{
    return v >= lo && v <= hi;
}

param_err_t params_set(ctrl_params_t *p, uint8_t id, int32_t v)
{
    switch (id) {
    case PARAM_KP:
        if (!in_range(v, 0, PID_GAIN_MAX)) return PARAM_ERR_RANGE;
        p->kp = v; break;
    case PARAM_KI:
        if (!in_range(v, 0, PID_GAIN_MAX)) return PARAM_ERR_RANGE;
        p->ki = v; break;
    case PARAM_KD:
        if (!in_range(v, 0, PID_GAIN_MAX)) return PARAM_ERR_RANGE;
        p->kd = v; break;
    case PARAM_LATENCY:
        if (!in_range(v, 0, (int32_t)EST_L_MAX)) return PARAM_ERR_RANGE;
        p->latency = (uint8_t)v; break;
    case PARAM_DEADBAND:
        if (!in_range(v, 0, 100)) return PARAM_ERR_RANGE;
        p->deadband = (uint8_t)v; break;
    case PARAM_D_SHIFT:
        if (!in_range(v, 0, PID_D_SHIFT_MAX)) return PARAM_ERR_RANGE;
        p->d_shift = (uint8_t)v; break;
    case PARAM_ID_AMP:
        if (!in_range(v, 1, 20)) return PARAM_ERR_RANGE;
        p->id_amp = (uint8_t)v; break;
    case PARAM_PLANT_GAIN:
        if (!in_range(v, PLANT_GAIN_MIN, PLANT_GAIN_MAX)) return PARAM_ERR_RANGE;
        p->plant_gain = v; break;
    case PARAM_EST_EN:
        if (!in_range(v, 0, 1)) return PARAM_ERR_RANGE;
        p->est_en = (v != 0); break;
    default:
        return PARAM_ERR_ID;
    }
    return PARAM_OK;
}

int32_t params_get(const ctrl_params_t *p, uint8_t id)
{
    switch (id) {
    case PARAM_KP:         return p->kp;
    case PARAM_KI:         return p->ki;
    case PARAM_KD:         return p->kd;
    case PARAM_LATENCY:    return p->latency;
    case PARAM_DEADBAND:   return p->deadband;
    case PARAM_D_SHIFT:    return p->d_shift;
    case PARAM_ID_AMP:     return p->id_amp;
    case PARAM_PLANT_GAIN: return p->plant_gain;
    case PARAM_EST_EN:     return p->est_en ? 1 : 0;
    default:               return 0;
    }
}
