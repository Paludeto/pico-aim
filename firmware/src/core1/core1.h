/* Core 1: so o controle deterministico. Um alarme de hardware a 1 kHz roda o
 * passo (ctrl/loop.c) inteiro dentro da IRQ. A troca de dados com o core 0 e
 * por filas (queue_t), sempre com try_add/try_remove: ninguem bloqueia. */
#ifndef CORE1_H
#define CORE1_H
#include <stdint.h>
#include <stdbool.h>
#include "../ctrl/loop.h"

void core1_start(void);                         /* cria as filas e lanca o core 1 */

/* Chamadas pelo core 0 */
bool core1_send_meas(const ctrl_meas_t *m);     /* false: fila cheia, medicao descartada */
bool core1_cmd_ready(void);                     /* ha espaco na fila de configuracao */
bool core1_send_cmd(const ctrl_cmd_t *c);
bool core1_recv_u(ctrl_u_t *u);
bool core1_recv_telem(ctrl_telem_t *t);
bool core1_alive(void);                         /* true se houve passo desde a ultima chamada */
uint32_t core1_overruns(void);                  /* passos perdidos (alarme atrasado) */

#endif
