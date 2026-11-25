/* Estimador do erro entre medicoes (multitaxa), portavel.
 *
 *   e^[k] = e_m - g * soma(u[i], i = k_c .. k-1)
 *
 * e_m chega a ~60 Hz e ja nasce atrasado: reflete o cursor no instante da
 * captura k_c = k_r - L. Ao receber a medicao, descontam-se os L ultimos
 * comandos (que a medicao ainda nao "viu"); depois, cada comando enviado e
 * descontado na hora. g e o ganho da planta em px por contagem (Q8.8).
 */
#ifndef ESTIMATOR_H
#define ESTIMATOR_H
#include <stdint.h>
#include <stdbool.h>

#define EST_HIST_LEN 128u              /* potencia de 2 */
#define EST_L_MAX    (EST_HIST_LEN - 1u)

typedef struct {
    int8_t hist[EST_HIST_LEN];
    uint8_t head;
    int32_t e_q8;       /* erro estimado, Q24.8 px */
    uint16_t gain_q8;   /* px por contagem, Q8.8 */
    bool enabled;       /* false => segura a ultima medicao (ZOH) */
} est_t;

void est_reset(est_t *s);
void est_measure(est_t *s, int16_t e_m, uint8_t latency_steps);
void est_apply(est_t *s, int8_t u);
int16_t est_get(const est_t *s);

#endif
