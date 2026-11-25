/* Protocolo PC <-> MCU sobre USB CDC (spec 7). Portavel. Little-endian.
 *
 *   A5 5A | TIPO | LEN | PAYLOAD (LEN bytes) | CRC8(TIPO .. PAYLOAD)
 *
 * PC -> MCU
 *   0x01 MEAS       SEQ(u8) FLAGS(u8, bit0: alvo valido) EX(i16) EY(i16)
 *   0x02 SET_PARAM  ID(u8) VALOR(i32)        ids e faixas em ctrl/params.h
 *   0x03 SET_MODE   MODO(u8)                 0 DESLIGADO, 1 AUTOMATICO, 2 IDENTIFICACAO
 *   0x04 SAVE       -                        so no estado DESLIGADO
 *   0x05 LOAD       -
 *   0x06 GET_PARAMS -                        resposta: PARAMS
 * MCU -> PC
 *   0x80 TELEM (28 bytes, 200 Hz)
 *        T_US(u32) TICK(u16) ESTADO(u8) FLAGS(u8) EMX EMY EHX EHY UX UY (i16)
 *        ERRS(u16) HID_DROP(u8) MEAS_AGE(u8) CARGA0 CARGA1 (u16, por mil)
 *        FLAGS = CTRL_FL_* (ctrl/loop.h); UX/UY = soma de u desde o quadro anterior
 *   0x81 ACK        TIPO de origem (u8) + codigo de erro (u8, 0 = ok)
 *   0x82 PARAMS     PARAM_COUNT x i32, na ordem dos ids
 * MEAS nao gera ACK. Pacotes invalidos sao descartados e contados em ERRS.
 */
#ifndef PROTO_H
#define PROTO_H
#include <stdint.h>
#include <stdbool.h>
#include "../ctrl/loop.h"

#define PROTO_SYNC0 0xA5
#define PROTO_SYNC1 0x5A

#define PROTO_T_MEAS       0x01
#define PROTO_T_SET_PARAM  0x02
#define PROTO_T_SET_MODE   0x03
#define PROTO_T_SAVE       0x04
#define PROTO_T_LOAD       0x05
#define PROTO_T_GET_PARAMS 0x06
#define PROTO_T_TELEM      0x80
#define PROTO_T_ACK        0x81
#define PROTO_T_PARAMS     0x82

#define PROTO_LEN_MEAS      6u
#define PROTO_LEN_SET_PARAM 5u
#define PROTO_LEN_SET_MODE  1u
#define PROTO_LEN_TELEM     28u
#define PROTO_LEN_ACK       2u
#define PROTO_LEN_PARAMS    (4u * PARAM_COUNT)

#define PROTO_OVERHEAD       5u     /* SYNC(2) + TIPO + LEN + CRC */
#define PROTO_RX_MAX_PAYLOAD 8u
#define PROTO_TX_MAX         (PROTO_LEN_PARAMS + PROTO_OVERHEAD)

/* codigos do ACK */
enum {
    PROTO_ERR_OK = 0,
    PROTO_ERR_TYPE,         /* tipo desconhecido */
    PROTO_ERR_LEN,          /* LEN errado para o tipo */
    PROTO_ERR_PARAM_ID,
    PROTO_ERR_RANGE,        /* valor fora da faixa */
    PROTO_ERR_MODE,
    PROTO_ERR_STATE,        /* SAVE fora do estado DESLIGADO */
    PROTO_ERR_STORAGE       /* flash: sem dados validos / falha na gravacao */
};

typedef struct {
    uint8_t type;
    uint8_t len;
    uint8_t payload[PROTO_RX_MAX_PAYLOAD];
} proto_frame_t;

typedef enum { PROTO_NONE = 0, PROTO_FRAME, PROTO_BAD_CRC, PROTO_BAD_LEN } proto_result_t;

typedef struct {
    uint8_t state;
    uint8_t idx;
    uint8_t crc;
    proto_frame_t f;
} proto_parser_t;

void proto_parser_init(proto_parser_t *p);
proto_result_t proto_parser_feed(proto_parser_t *p, uint8_t byte, proto_frame_t *out);

int16_t proto_get_i16(const uint8_t *p);
int32_t proto_get_i32(const uint8_t *p);

/* Montam um quadro em buf (>= PROTO_TX_MAX bytes) e devolvem o tamanho. */
uint8_t proto_build_telem(uint8_t *buf, const ctrl_telem_t *t, uint16_t errs, uint16_t load0);
uint8_t proto_build_ack(uint8_t *buf, uint8_t src_type, uint8_t err);
uint8_t proto_build_params(uint8_t *buf, const ctrl_params_t *p);

#endif
