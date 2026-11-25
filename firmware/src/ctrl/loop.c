#include "loop.h"

/* Sequencia de identificacao, em passos de 1 ms:
 * zero | +A | zero | -A | zero | PRBS7 (127 chips de 20 ms) | zero */
#define ID_ZERO   200u
#define ID_STEP   250u
#define ID_CHIP   20u
#define ID_CHIPS  127u
#define ID_T1 (ID_ZERO)
#define ID_T2 (ID_T1 + ID_STEP)
#define ID_T3 (ID_T2 + ID_ZERO)
#define ID_T4 (ID_T3 + ID_STEP)
#define ID_T5 (ID_T4 + ID_ZERO)
#define ID_T6 (ID_T5 + ID_CHIP * ID_CHIPS)
#define ID_T7 (ID_T6 + ID_ZERO)

static void apply_params(ctrl_loop_t *c, const ctrl_params_t *p)
{
    c->p = *p;
    c->cfg.kp = p->kp;
    c->cfg.ki = p->ki;
    c->cfg.kd = p->kd;
    c->cfg.deadband = p->deadband;
    c->cfg.d_shift = p->d_shift;
    for (uint8_t a = 0; a < 2; a++) {
        c->est[a].gain_q8 = (uint16_t)(p->plant_gain >> 8);
        c->est[a].enabled = p->est_en;
    }
}

static void reset_pid(ctrl_loop_t *c)
{
    pid_reset(&c->pid[0]);
    pid_reset(&c->pid[1]);
}

/* Transicao de estado: integrador, historico e acumuladores zerados. */
static void reset_all(ctrl_loop_t *c)
{
    reset_pid(c);
    est_reset(&c->est[0]);
    est_reset(&c->est[1]);
    c->id_n = 0;
}

void ctrl_loop_init(ctrl_loop_t *c)
{
    ctrl_params_t p;
    params_defaults(&p);
    apply_params(c, &p);
    c->state = CTRL_OFF;
    c->enabled = false;
    c->ident_done = false;
    c->link_ok = false;
    c->target_valid = false;
    c->link_cnt = CTRL_LINK_TIMEOUT_STEPS;
    c->meas_age = 255;
    c->tick = 0;
    c->em_x = c->em_y = 0;
    reset_all(c);
    c->lfsr = 0x7F;
    c->id_chip = 0;
    c->hid_drop = 0;
    c->usum_x = c->usum_y = 0;
    c->telem_div = 0;
}

/* Proxima amostra da identificacao. Retorna false quando termina. */
static bool ident_next(ctrl_loop_t *c, int8_t *u)
{
    uint16_t n = c->id_n++;
    int8_t a = (int8_t)c->p.id_amp;
    if (n == 0) {
        c->lfsr = 0x7F;
        c->id_chip = a;
    }
    if (n < ID_T1)      *u = 0;
    else if (n < ID_T2) *u = a;
    else if (n < ID_T3) *u = 0;
    else if (n < ID_T4) *u = (int8_t)-a;
    else if (n < ID_T5) *u = 0;
    else if (n < ID_T6) {
        if ((n - ID_T5) % ID_CHIP == 0) {       /* PRBS7: x^7 + x^6 + 1 */
            uint8_t bit = (uint8_t)(((c->lfsr >> 6) ^ (c->lfsr >> 5)) & 1u);
            c->lfsr = (uint8_t)(((c->lfsr << 1) | bit) & 0x7F);
            c->id_chip = bit ? a : (int8_t)-a;
        }
        *u = c->id_chip;
    } else if (n < ID_T7) *u = 0;
    else return false;
    return true;
}

unsigned ctrl_loop_step(ctrl_loop_t *c, const ctrl_cmd_t *cmd, const ctrl_meas_t *meas,
                        bool out_ready, ctrl_u_t *u, ctrl_telem_t *telem)
{
    unsigned out = 0;
    c->tick++;

    /* 1. configuracao nova: parametros, modo e habilitacao, de uma vez */
    if (cmd) {
        uint8_t mode = cmd->mode < CTRL_NSTATES ? cmd->mode : CTRL_OFF;
        if (mode != CTRL_IDENT)
            c->ident_done = false;
        else if (c->ident_done)
            mode = CTRL_OFF;                    /* ja rodou: espera o modo mudar */
        apply_params(c, &cmd->params);
        if (mode != c->state || cmd->enable != c->enabled) {
            c->state = mode;
            c->enabled = cmd->enable;
            reset_all(c);
        }
    }

    /* 2. medicao nova / failsafe de link */
    if (meas) {
        c->target_valid = (meas->flags & CTRL_MEAS_VALID) != 0;
        if (c->target_valid) {
            c->em_x = meas->ex;
            c->em_y = meas->ey;
            est_measure(&c->est[0], meas->ex, c->p.latency);
            est_measure(&c->est[1], meas->ey, c->p.latency);
        }
        c->link_cnt = 0;
        c->meas_age = 0;
        c->link_ok = true;
    } else {
        if (c->link_cnt < 255) c->link_cnt++;
        if (c->meas_age < 255) c->meas_age++;
    }
    if (c->link_cnt >= CTRL_LINK_TIMEOUT_STEPS)
        c->link_ok = false;

    /* 3. lei de controle */
    int8_t ux = 0, uy = 0;
    if (c->state == CTRL_AUTO) {
        if (!c->enabled || !c->link_ok) {
            reset_pid(c);                       /* u = 0, integrador zerado */
        } else if (c->target_valid) {
            ux = pid_step(&c->pid[0], &c->cfg, est_get(&c->est[0]));
            uy = pid_step(&c->pid[1], &c->cfg, est_get(&c->est[1]));
        }                                       /* alvo invalido: u = 0, integrador congelado */
    } else if (c->state == CTRL_IDENT) {
        if (!c->enabled) {
            c->id_n = 0;                        /* espera habilitar */
        } else if (ident_next(c, &ux)) {
            uy = ux;
        } else {
            ux = 0;
            c->state = CTRL_OFF;
            c->ident_done = true;
        }
    }

    /* 4. saida */
    if (ux != 0 || uy != 0) {
        if (out_ready) {
            out |= CTRL_OUT_U;
        } else {
            ux = uy = 0;
            if (c->hid_drop < 255) c->hid_drop++;
        }
    }
    u->dx = ux;
    u->dy = uy;
    est_apply(&c->est[0], ux);
    est_apply(&c->est[1], uy);

    /* 5. telemetria decimada */
    c->usum_x += ux;
    c->usum_y += uy;
    if (++c->telem_div >= CTRL_TELEM_DIV) {
        c->telem_div = 0;
        telem->t_us = 0;
        telem->tick = c->tick;
        telem->state = c->state;
        telem->flags = (uint8_t)((c->enabled ? CTRL_FL_ENABLED : 0)
                     | (c->link_ok ? CTRL_FL_LINK_OK : 0)
                     | (c->target_valid ? CTRL_FL_TARGET : 0)
                     | (c->p.est_en ? CTRL_FL_EST_ON : 0)
                     | (c->ident_done ? CTRL_FL_IDENT_DONE : 0)
                     | ((c->pid[0].saturated || c->pid[1].saturated) ? CTRL_FL_SATURATED : 0));
        telem->em_x = c->em_x;
        telem->em_y = c->em_y;
        telem->eh_x = est_get(&c->est[0]);
        telem->eh_y = est_get(&c->est[1]);
        telem->u_x = c->usum_x;
        telem->u_y = c->usum_y;
        telem->hid_drop = c->hid_drop;
        telem->meas_age = c->meas_age;
        telem->load1 = 0;
        c->usum_x = c->usum_y = 0;
        out |= CTRL_OUT_TELEM;
    }
    return out;
}
