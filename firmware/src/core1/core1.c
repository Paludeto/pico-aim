#include "core1.h"
#include "pico/stdlib.h"
#include "pico/multicore.h"
#include "pico/util/queue.h"
#include "hardware/timer.h"
#include "hardware/sync.h"
#include "board_config.h"

#if CTRL_PERIOD_US * CTRL_HZ != 1000000u
#error "CTRL_PERIOD_US (board_config.h) e CTRL_HZ (ctrl/loop.h) nao batem"
#endif

static queue_t q_meas, q_cmd;       /* core 0 -> core 1 */
static queue_t q_u, q_telem;        /* core 1 -> core 0 */

static ctrl_loop_t loop;
static uint alarm_num;
static absolute_time_t next_step;
static uint32_t busy_us;            /* tempo dentro da IRQ desde a ultima telemetria */
static volatile uint32_t beat;
static volatile uint32_t overruns;

/* IRQ do alarme, 1 kHz, no core 1. Todo o caminho roda da RAM (o binario e
 * copy_to_ram), entao a leitura do BOOTSEL no core 0, que tira a flash do ar
 * por alguns us, nao atrasa o controle. */
static void __not_in_flash_func(ctrl_alarm_irq)(uint num)
{
    uint32_t t0 = time_us_32();
    gpio_put(DBG_PIN_CTRL, 1);

    /* Rearma por tempo absoluto: o periodo nao acumula o atraso da IRQ. Se o
     * alvo ja passou (core pausado na gravacao da flash), ressincroniza. */
    next_step = delayed_by_us(next_step, CTRL_PERIOD_US);
    while (hardware_alarm_set_target(num, next_step)) {
        next_step = make_timeout_time_us(CTRL_PERIOD_US);
        overruns++;
    }

    /* So a mensagem mais nova de cada fila interessa. */
    ctrl_cmd_t cmd;
    ctrl_meas_t meas;
    bool has_cmd = false, has_meas = false;
    while (queue_try_remove(&q_cmd, &cmd))
        has_cmd = true;
    while (queue_try_remove(&q_meas, &meas))
        has_meas = true;

    ctrl_u_t u;
    ctrl_telem_t telem;
    unsigned out = ctrl_loop_step(&loop, has_cmd ? &cmd : NULL, has_meas ? &meas : NULL,
                                  !queue_is_full(&q_u), &u, &telem);
    if (out & CTRL_OUT_U)
        (void)queue_try_add(&q_u, &u);
    if (out & CTRL_OUT_TELEM) {
        telem.t_us = t0;
        telem.load1 = (uint16_t)(busy_us * 1000u / (CTRL_TELEM_DIV * CTRL_PERIOD_US));
        busy_us = 0;
        (void)queue_try_add(&q_telem, &telem);  /* cheia: o core 0 esta atrasado, descarta */
    }

    beat++;
    gpio_put(DBG_PIN_CTRL, 0);
    busy_us += time_us_32() - t0;
}

static void core1_main(void)
{
    /* Permite ao core 0 pausar este nucleo durante a gravacao da flash. */
    multicore_lockout_victim_init();

    /* Chamado daqui, o SDK habilita a IRQ do alarme no NVIC do core 1. */
    alarm_num = (uint)hardware_alarm_claim_unused(true);
    hardware_alarm_set_callback(alarm_num, ctrl_alarm_irq);
    next_step = make_timeout_time_us(CTRL_PERIOD_US);
    while (hardware_alarm_set_target(alarm_num, next_step))
        next_step = make_timeout_time_us(CTRL_PERIOD_US);

    for (;;)
        __wfi();
}

void core1_start(void)
{
    gpio_init(DBG_PIN_CTRL);
    gpio_set_dir(DBG_PIN_CTRL, GPIO_OUT);

    queue_init(&q_meas, sizeof(ctrl_meas_t), Q_MEAS_LEN);
    queue_init(&q_cmd, sizeof(ctrl_cmd_t), Q_CMD_LEN);
    queue_init(&q_u, sizeof(ctrl_u_t), Q_U_LEN);
    queue_init(&q_telem, sizeof(ctrl_telem_t), Q_TELEM_LEN);
    ctrl_loop_init(&loop);
    multicore_launch_core1(core1_main);
}

bool core1_send_meas(const ctrl_meas_t *m) { return queue_try_add(&q_meas, m); }
bool core1_cmd_ready(void)                 { return !queue_is_full(&q_cmd); }
bool core1_send_cmd(const ctrl_cmd_t *c)   { return queue_try_add(&q_cmd, c); }
bool core1_recv_u(ctrl_u_t *u)             { return queue_try_remove(&q_u, u); }
bool core1_recv_telem(ctrl_telem_t *t)     { return queue_try_remove(&q_telem, t); }

bool core1_alive(void)
{
    static uint32_t seen;
    uint32_t b = beat;
    bool alive = (b != seen);
    seen = b;
    return alive;
}

uint32_t core1_overruns(void)
{
    return overruns;
}
