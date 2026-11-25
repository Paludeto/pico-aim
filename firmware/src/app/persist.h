/* Persistencia dos parametros (spec 6.5). No RP2040: ultimo setor da flash
 * (persist.c). Nos testes do PC: stub em RAM. */
#ifndef PERSIST_H
#define PERSIST_H
#include <stdbool.h>
#include "../ctrl/params.h"

/* So pode ser chamada no estado DESLIGADO (pausa o core 1). */
bool persist_save(const ctrl_params_t *p);
/* false se nao houver copia valida (magico, versao, CRC e faixas). */
bool persist_load(ctrl_params_t *p);

#endif
