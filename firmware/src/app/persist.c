/* Parametros no ultimo setor da flash (spec 6.5).
 *
 *   MAGICO(u32) | VERSAO(u16) | N(u16) | N x i32 (na ordem dos ids) | CRC8
 *
 * Apagar/gravar tira a flash do ar: o core 1 e pausado com multicore_lockout
 * (com timeout) e as interrupcoes do core 0 ficam desligadas. A aplicacao so
 * chama persist_save() no estado DESLIGADO. */
#include <string.h>
#include "persist.h"
#include "../proto/crc8.h"
#include "pico/stdlib.h"
#include "pico/multicore.h"
#include "hardware/flash.h"
#include "hardware/sync.h"
#include "hardware/watchdog.h"

#define PERSIST_MAGIC   0x4B525443u         /* "CTRK" */
#define PERSIST_VERSION 1u
#define PERSIST_OFFSET  (PICO_FLASH_SIZE_BYTES - FLASH_SECTOR_SIZE)
#define PERSIST_HDR     8u
#define PERSIST_LEN     (PERSIST_HDR + 4u * PARAM_COUNT + 1u)
#define LOCKOUT_TIMEOUT_US 100000u

static void put32(uint8_t *p, uint32_t v)
{
    p[0] = (uint8_t)v; p[1] = (uint8_t)(v >> 8); p[2] = (uint8_t)(v >> 16); p[3] = (uint8_t)(v >> 24);
}

static uint32_t get32(const uint8_t *p)
{
    return (uint32_t)p[0] | ((uint32_t)p[1] << 8) | ((uint32_t)p[2] << 16) | ((uint32_t)p[3] << 24);
}

static const uint8_t *stored(void)
{
    return (const uint8_t *)(XIP_BASE + PERSIST_OFFSET);
}

bool persist_load(ctrl_params_t *p)
{
    const uint8_t *s = stored();
    ctrl_params_t tmp;

    if (get32(s) != PERSIST_MAGIC || get32(s + 4) != (PERSIST_VERSION | ((uint32_t)PARAM_COUNT << 16)))
        return false;
    if (crc8(s, PERSIST_LEN - 1u) != s[PERSIST_LEN - 1u])
        return false;
    params_defaults(&tmp);
    for (uint8_t id = 1; id <= PARAM_COUNT; id++)
        if (params_set(&tmp, id, (int32_t)get32(s + PERSIST_HDR + 4u * (id - 1u))) != PARAM_OK)
            return false;
    *p = tmp;
    return true;
}

bool persist_save(const ctrl_params_t *p)
{
    static uint8_t page[FLASH_PAGE_SIZE];

    memset(page, 0xFF, sizeof page);
    put32(page, PERSIST_MAGIC);
    put32(page + 4, PERSIST_VERSION | ((uint32_t)PARAM_COUNT << 16));
    for (uint8_t id = 1; id <= PARAM_COUNT; id++)
        put32(page + PERSIST_HDR + 4u * (id - 1u), (uint32_t)params_get(p, id));
    page[PERSIST_LEN - 1u] = crc8(page, PERSIST_LEN - 1u);

    if (memcmp(stored(), page, sizeof page) == 0)
        return true;                        /* nada mudou: poupa a flash */

    watchdog_update();
    if (!multicore_lockout_start_timeout_us(LOCKOUT_TIMEOUT_US))
        return false;
    uint32_t irq = save_and_disable_interrupts();
    flash_range_erase(PERSIST_OFFSET, FLASH_SECTOR_SIZE);
    flash_range_program(PERSIST_OFFSET, page, sizeof page);
    restore_interrupts(irq);
    (void)multicore_lockout_end_timeout_us(LOCKOUT_TIMEOUT_US);
    watchdog_update();

    return memcmp(stored(), page, sizeof page) == 0;
}
