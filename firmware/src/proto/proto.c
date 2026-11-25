#include "proto.h"
#include "crc8.h"

enum { S_SYNC0 = 0, S_SYNC1, S_TYPE, S_LEN, S_PAYLOAD, S_CRC };

void proto_parser_init(proto_parser_t *p)
{
    p->state = S_SYNC0;
    p->idx = 0;
    p->crc = 0;
}

proto_result_t proto_parser_feed(proto_parser_t *p, uint8_t byte, proto_frame_t *out)
{
    switch (p->state) {
    case S_SYNC0:
        if (byte == PROTO_SYNC0)
            p->state = S_SYNC1;
        break;
    case S_SYNC1:
        if (byte == PROTO_SYNC1)
            p->state = S_TYPE;
        else if (byte != PROTO_SYNC0)
            p->state = S_SYNC0;
        break;
    case S_TYPE:
        p->f.type = byte;
        p->crc = crc8_update(0, byte);
        p->state = S_LEN;
        break;
    case S_LEN:
        if (byte > PROTO_RX_MAX_PAYLOAD) {
            p->state = S_SYNC0;
            return PROTO_BAD_LEN;
        }
        p->f.len = byte;
        p->crc = crc8_update(p->crc, byte);
        p->idx = 0;
        p->state = byte ? S_PAYLOAD : S_CRC;
        break;
    case S_PAYLOAD:
        p->f.payload[p->idx++] = byte;
        p->crc = crc8_update(p->crc, byte);
        if (p->idx >= p->f.len)
            p->state = S_CRC;
        break;
    default:
        p->state = S_SYNC0;
        if (p->crc != byte)
            return PROTO_BAD_CRC;
        *out = p->f;
        return PROTO_FRAME;
    }
    return PROTO_NONE;
}

int16_t proto_get_i16(const uint8_t *p)
{
    return (int16_t)((uint16_t)p[0] | ((uint16_t)p[1] << 8));
}

int32_t proto_get_i32(const uint8_t *p)
{
    return (int32_t)((uint32_t)p[0] | ((uint32_t)p[1] << 8) | ((uint32_t)p[2] << 16) | ((uint32_t)p[3] << 24));
}

static uint8_t *put16(uint8_t *p, uint16_t v)
{
    *p++ = (uint8_t)v;
    *p++ = (uint8_t)(v >> 8);
    return p;
}

static uint8_t *put32(uint8_t *p, uint32_t v)
{
    p = put16(p, (uint16_t)v);
    return put16(p, (uint16_t)(v >> 16));
}

static uint8_t *begin(uint8_t *buf, uint8_t type, uint8_t len)
{
    buf[0] = PROTO_SYNC0;
    buf[1] = PROTO_SYNC1;
    buf[2] = type;
    buf[3] = len;
    return buf + 4;
}

static uint8_t finish(uint8_t *buf, uint8_t *end)
{
    *end = crc8(buf + 2, (uint8_t)(end - buf - 2));
    return (uint8_t)(end - buf + 1);
}

uint8_t proto_build_telem(uint8_t *buf, const ctrl_telem_t *t, uint16_t errs, uint16_t load0)
{
    uint8_t *p = begin(buf, PROTO_T_TELEM, PROTO_LEN_TELEM);
    p = put32(p, t->t_us);
    p = put16(p, t->tick);
    *p++ = t->state;
    *p++ = t->flags;
    p = put16(p, (uint16_t)t->em_x);
    p = put16(p, (uint16_t)t->em_y);
    p = put16(p, (uint16_t)t->eh_x);
    p = put16(p, (uint16_t)t->eh_y);
    p = put16(p, (uint16_t)t->u_x);
    p = put16(p, (uint16_t)t->u_y);
    p = put16(p, errs);
    *p++ = t->hid_drop;
    *p++ = t->meas_age;
    p = put16(p, load0);
    p = put16(p, t->load1);
    return finish(buf, p);
}

uint8_t proto_build_ack(uint8_t *buf, uint8_t src_type, uint8_t err)
{
    uint8_t *p = begin(buf, PROTO_T_ACK, PROTO_LEN_ACK);
    *p++ = src_type;
    *p++ = err;
    return finish(buf, p);
}

uint8_t proto_build_params(uint8_t *buf, const ctrl_params_t *prm)
{
    uint8_t *p = begin(buf, PROTO_T_PARAMS, (uint8_t)PROTO_LEN_PARAMS);
    for (uint8_t id = 1; id <= PARAM_COUNT; id++)
        p = put32(p, (uint32_t)params_get(prm, id));
    return finish(buf, p);
}
