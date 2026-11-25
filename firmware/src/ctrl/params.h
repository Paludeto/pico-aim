/* Parametros do controlador: valores padrao, faixas validas e acesso por ID
 * (comando SET_PARAM / GET_PARAMS). Portavel.
 *
 * Todos os valores viajam como int32. Ganhos em Q16.16 "por amostra":
 *   KP = Kp [contagens/px], KI = Ki*T, KD = Kd/T, com T = 1 ms.
 */
#ifndef PARAMS_H
#define PARAMS_H
#include <stdint.h>
#include <stdbool.h>
#include "fixed.h"

enum {
    PARAM_KP         = 1,   /* Q16.16, 0 .. <16 */
    PARAM_KI         = 2,   /* Q16.16 por amostra, 0 .. <16 */
    PARAM_KD         = 3,   /* Q16.16 por amostra, 0 .. <16 */
    PARAM_LATENCY    = 4,   /* L em periodos de controle, 0 .. 127 */
    PARAM_DEADBAND   = 5,   /* px, 0 .. 100 */
    PARAM_D_SHIFT    = 6,   /* filtro da derivada (alfa = 2^-n), 0 .. 8 */
    PARAM_ID_AMP     = 7,   /* amplitude da identificacao, contagens, 1 .. 20 */
    PARAM_PLANT_GAIN = 8,   /* px por contagem, Q16.16, 0,125 .. 8 */
    PARAM_EST_EN     = 9    /* estimador: 0 desligado (ZOH), 1 ligado */
};
#define PARAM_COUNT 9u      /* IDs validos: 1 .. PARAM_COUNT */

typedef enum { PARAM_OK = 0, PARAM_ERR_ID, PARAM_ERR_RANGE } param_err_t;

typedef struct {
    q16_t kp, ki, kd;
    q16_t plant_gain;
    uint8_t latency;
    uint8_t deadband;
    uint8_t d_shift;
    uint8_t id_amp;
    bool est_en;
} ctrl_params_t;

void params_defaults(ctrl_params_t *p);
/* Valida a faixa; so altera *p se o valor for aceito. */
param_err_t params_set(ctrl_params_t *p, uint8_t id, int32_t v);
int32_t params_get(const ctrl_params_t *p, uint8_t id);

#endif
