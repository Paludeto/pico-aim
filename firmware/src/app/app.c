#include "app.h"
#include "persist.h"

static struct {
    ctrl_params_t params;
    uint8_t mode;
    bool enabled;
    bool dirty;             /* ha configuracao nova para o core 1 */
    bool usb_ok;
    bool link_ok;
    uint8_t core_state;
    uint8_t last_seq;
    bool have_seq;
    uint16_t errs;
} a;

void app_init(void)
{
    ctrl_params_t saved;
    params_defaults(&a.params);
    if (persist_load(&saved))
        a.params = saved;
    a.mode = CTRL_OFF;
    a.enabled = false;
    a.dirty = true;
    a.usb_ok = false;
    a.link_ok = false;
    a.core_state = CTRL_OFF;
    a.have_seq = false;
    a.last_seq = 0;
    a.errs = 0;
}

static void count_error(void)
{
    if (a.errs < 0xFFFF)
        a.errs++;
}

void app_on_proto_error(void)
{
    count_error();
}

static void force_off(void)
{
    if (a.mode != CTRL_OFF || a.enabled) {
        a.mode = CTRL_OFF;
        a.enabled = false;
        a.dirty = true;
    }
}

/* Sequencia: aceita avancos de 1..127 (mod 256). Com o link caido, qualquer
 * SEQ ressincroniza. */
static bool on_meas(const proto_frame_t *f, ctrl_meas_t *meas)
{
    uint8_t seq = f->payload[0];
    if (a.have_seq && a.link_ok) {
        uint8_t d = (uint8_t)(seq - a.last_seq);
        if (d == 0 || d >= 128) {
            count_error();
            return false;
        }
    }
    a.last_seq = seq;
    a.have_seq = true;
    meas->flags = f->payload[1];
    meas->ex = proto_get_i16(&f->payload[2]);
    meas->ey = proto_get_i16(&f->payload[4]);
    return true;
}

static uint8_t on_set_param(const proto_frame_t *f)
{
    switch (params_set(&a.params, f->payload[0], proto_get_i32(&f->payload[1]))) {
    case PARAM_OK:     a.dirty = true; return PROTO_ERR_OK;
    case PARAM_ERR_ID: return PROTO_ERR_PARAM_ID;
    default:           return PROTO_ERR_RANGE;
    }
}

static uint8_t on_set_mode(const proto_frame_t *f)
{
    if (f->payload[0] >= CTRL_NSTATES)
        return PROTO_ERR_MODE;
    a.mode = f->payload[0];
    a.dirty = true;
    return PROTO_ERR_OK;
}

static uint8_t on_save(void)
{
    if (a.mode != CTRL_OFF || a.core_state != CTRL_OFF)
        return PROTO_ERR_STATE;
    return persist_save(&a.params) ? PROTO_ERR_OK : PROTO_ERR_STORAGE;
}

static uint8_t on_load(void)
{
    ctrl_params_t saved;
    if (!persist_load(&saved))
        return PROTO_ERR_STORAGE;
    a.params = saved;
    a.dirty = true;
    return PROTO_ERR_OK;
}

bool app_on_frame(const proto_frame_t *f, ctrl_meas_t *meas, uint8_t *resp, uint8_t *resp_len)
{
    static const struct { uint8_t type, len; } lens[] = {
        { PROTO_T_MEAS, PROTO_LEN_MEAS },   { PROTO_T_SET_PARAM, PROTO_LEN_SET_PARAM },
        { PROTO_T_SET_MODE, PROTO_LEN_SET_MODE }, { PROTO_T_SAVE, 0 },
        { PROTO_T_LOAD, 0 },                { PROTO_T_GET_PARAMS, 0 },
    };
    uint8_t err = PROTO_ERR_TYPE;
    *resp_len = 0;

    for (uint8_t i = 0; i < sizeof lens / sizeof lens[0]; i++)
        if (lens[i].type == f->type)
            err = (lens[i].len == f->len) ? PROTO_ERR_OK : PROTO_ERR_LEN;

    if (err == PROTO_ERR_OK) {
        switch (f->type) {
        case PROTO_T_MEAS:
            return on_meas(f, meas);
        case PROTO_T_SET_PARAM: err = on_set_param(f); break;
        case PROTO_T_SET_MODE:  err = on_set_mode(f);  break;
        case PROTO_T_SAVE:      err = on_save();       break;
        case PROTO_T_LOAD:      err = on_load();       break;
        default:                /* GET_PARAMS */
            *resp_len = proto_build_params(resp, &a.params);
            return false;
        }
    }
    if (err != PROTO_ERR_OK)
        count_error();
    *resp_len = proto_build_ack(resp, f->type, err);
    return false;
}

void app_on_button(app_button_t b)
{
    if (b == APP_BTN_LONG) {
        force_off();                        /* parada de emergencia */
    } else if (a.usb_ok) {
        a.enabled = !a.enabled;
        a.dirty = true;
    }
}

void app_on_usb(bool ready)
{
    a.usb_ok = ready;
    if (!ready)
        force_off();
}

void app_on_telem(const ctrl_telem_t *t)
{
    a.link_ok = (t->flags & CTRL_FL_LINK_OK) != 0;
    a.core_state = t->state;
    if ((t->flags & CTRL_FL_IDENT_DONE) && a.mode == CTRL_IDENT) {
        a.mode = CTRL_OFF;                  /* identificacao terminou */
        a.dirty = true;
    }
}

bool app_cmd_pending(void)
{
    return a.dirty;
}

void app_take_cmd(ctrl_cmd_t *cmd)
{
    cmd->params = a.params;
    cmd->mode = a.mode;
    cmd->enable = a.enabled;
    a.dirty = false;
}

void app_get_status(app_status_t *st)
{
    st->mode = a.mode;
    st->core_state = a.core_state;
    st->enabled = a.enabled;
    st->usb_ok = a.usb_ok;
    st->link_ok = a.link_ok;
    st->errs = a.errs;
}
